import asyncio
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Set

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from starlette.responses import JSONResponse

# Import core components from the main server
from app.core.container import global_container
from app.core.settings import set_execution_approval_mode, settings
from app.tools.execution import place_cex_order, swap_tokens, transfer_eth
from errors import InternalError, ReadyTraderError, json_error_response
from execution.cex_executor import CexExecutor
from execution.evm import get_web3
from marketdata.store import TickerSnapshot
from observability import build_log_context, log_event
from rate_limiter import RateLimitError

# JWT support (optional, for multi-user scenarios)
try:
    import jwt

    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False

# Password hashing support (bcrypt via passlib)
try:
    from passlib.hash import bcrypt

    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False

# Initial context
API_CTX = build_log_context(tool="api_server")

app = FastAPI(
    title="ReadyTrader-Crypto API",
    description="Production-grade API for AI-powered crypto trading with safety guardrails",
    version=settings.VERSION,
)

# Security configuration
security = HTTPBearer(auto_error=False)

# JWT configuration - require explicit secret in production
if settings.DEV_MODE:
    JWT_SECRET = settings.API_JWT_SECRET or secrets.token_hex(32)
else:
    JWT_SECRET = settings.API_JWT_SECRET
    if settings.API_AUTH_REQUIRED and not JWT_SECRET:
        raise RuntimeError("API_JWT_SECRET must be set when API_AUTH_REQUIRED=true in production mode. Set DEV_MODE=true for development.")

JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = settings.API_JWT_EXPIRATION_HOURS

# CORS configuration - strict by default in production
if settings.DEV_MODE or settings.CORS_ALLOW_ALL:
    cors_origins = ["*"]
else:
    cors_origins = list(settings.CORS_ORIGINS) if settings.CORS_ORIGINS else ["http://localhost:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    allow_credentials=not settings.CORS_ALLOW_ALL,  # No credentials with wildcard
    max_age=600,  # Cache preflight for 10 minutes
)


# -----------------------------------------------------------------------------
# Security Headers Middleware
# -----------------------------------------------------------------------------
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Add security headers to all responses."""
    response = await call_next(request)

    # Security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    if not settings.DEV_MODE:
        # HSTS in production
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    return response


# -----------------------------------------------------------------------------
# Rate Limiting Middleware
# -----------------------------------------------------------------------------
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Apply rate limiting to all HTTP requests."""
    if not settings.RATE_LIMIT_ENABLED:
        return await call_next(request)

    # Get client identifier (IP or authenticated user)
    client_ip = request.client.host if request.client else "unknown"
    auth_header = request.headers.get("authorization", "")

    # Use authenticated user ID if available, else IP
    rate_key = f"api:{client_ip}"
    if auth_header.startswith("Bearer ") and JWT_AVAILABLE and JWT_SECRET:
        try:
            token = auth_header[7:]
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            rate_key = f"api:user:{payload.get('sub', client_ip)}"
        except Exception:
            pass

    try:
        global_container.rate_limiter.check(key=rate_key, limit=settings.RATE_LIMIT_DEFAULT_PER_MIN, window_seconds=60)
    except RateLimitError:
        log_event("rate_limit_exceeded", ctx=API_CTX, data={"key": rate_key})
        from errors import RateLimitError as RTRateLimitError

        error = RTRateLimitError(key=rate_key, limit=settings.RATE_LIMIT_DEFAULT_PER_MIN, window_seconds=60, current_count=0)
        return JSONResponse(status_code=429, content=json_error_response(error), headers={"Retry-After": "60"})

    return await call_next(request)


# -----------------------------------------------------------------------------
# Authentication Helpers
# -----------------------------------------------------------------------------
def create_access_token(user_id: str, additional_claims: dict = None) -> str:
    """Create a JWT access token."""
    if not JWT_AVAILABLE:
        raise HTTPException(status_code=500, detail="JWT support not available. Install pyjwt.")

    if not JWT_SECRET:
        raise HTTPException(status_code=500, detail="JWT secret not configured")

    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(hours=JWT_EXPIRATION_HOURS),
        "type": "access",
    }
    if additional_claims:
        payload.update(additional_claims)

    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against bcrypt hash."""
    if not BCRYPT_AVAILABLE:
        # Fallback to plaintext comparison in dev mode only
        if settings.DEV_MODE:
            return plain_password == hashed_password
        raise HTTPException(status_code=500, detail="Password hashing not available. Install passlib[bcrypt].")

    try:
        return bcrypt.verify(plain_password, hashed_password)
    except Exception:
        return False


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    if not BCRYPT_AVAILABLE:
        raise HTTPException(status_code=500, detail="Password hashing not available. Install passlib[bcrypt].")
    return bcrypt.hash(password)


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Optional[dict]:
    """Verify JWT token and return payload."""
    if not credentials:
        return None

    if not JWT_AVAILABLE:
        return None

    if not JWT_SECRET:
        return None

    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def require_auth(token_payload: Optional[dict] = Depends(verify_token)) -> dict:
    """Require authentication for endpoint."""
    if not settings.API_AUTH_REQUIRED:
        return {"sub": "anonymous", "role": "user"}

    if not token_payload:
        raise HTTPException(status_code=401, detail="Authentication required")

    return token_payload


def require_admin(token_payload: dict = Depends(require_auth)) -> dict:
    """Require admin role for endpoint."""
    if token_payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return token_payload


# Active WebSocket connections
active_connections: Set[WebSocket] = set()


def broadcast_tick(snap: TickerSnapshot):
    """
    Callback for marketdata_ws_store updates.
    """
    if not active_connections:
        return

    payload = {"type": "TICKER_UPDATE", "data": snap.to_dict()}

    # We need to run this in the event loop of the FastAPI app
    # Since this callback might be triggered from a background thread
    # We use a global loop reference or call_soon_threadsafe
    loop = asyncio.get_event_loop()
    if loop.is_running():
        loop.create_task(broadcast_all(payload))


async def broadcast_all(payload: dict):
    if not active_connections:
        return
    message = json.dumps(payload)
    disconnected = set()
    for websocket in active_connections:
        try:
            await websocket.send_text(message)
        except Exception:
            disconnected.add(websocket)

    for ws in disconnected:
        active_connections.remove(ws)


# Subscribe to ticker updates from the WebSocket store
global_container.marketdata_ws_store.subscribe(broadcast_tick)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.add(websocket)
    log_event("api_client_connected", ctx=API_CTX, data={"active_connections": len(active_connections)})
    try:
        while True:
            # Keep connection open
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.remove(websocket)
        log_event("api_client_disconnected", ctx=API_CTX, data={"active_connections": len(active_connections)})


@app.get("/api/health")
async def health_check():
    """Health check endpoint - no authentication required."""
    return {
        "status": "ok",
        "mode": "paper" if settings.PAPER_MODE else "live",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": settings.VERSION,
        "trading_halted": settings.TRADING_HALTED,
        "live_enabled": settings.LIVE_TRADING_ENABLED,
    }


# -----------------------------------------------------------------------------
# Authentication Endpoints
# -----------------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


@app.post("/api/auth/login", response_model=TokenResponse)
async def login(request: LoginRequest):
    """
    Authenticate and receive a JWT token.

    In production mode:
    - Requires API_ADMIN_PASSWORD_HASH (bcrypt hash)
    - Set hash using: python -c "from passlib.hash import bcrypt; print(bcrypt.hash('your-password'))"

    In dev mode:
    - Falls back to plaintext API_ADMIN_PASSWORD if hash not set
    """
    admin_user = settings.API_ADMIN_USERNAME
    admin_pass_hash = settings.API_ADMIN_PASSWORD_HASH
    admin_pass_plain = os.getenv("API_ADMIN_PASSWORD", "")

    # Check if any credentials are configured
    if not admin_pass_hash and not admin_pass_plain:
        raise HTTPException(status_code=501, detail="Authentication not configured. Set API_ADMIN_PASSWORD_HASH (recommended) or API_ADMIN_PASSWORD.")

    # Verify username
    if request.username != admin_user:
        log_event("auth_failed", ctx=API_CTX, data={"reason": "invalid_username"})
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Verify password
    password_valid = False

    if admin_pass_hash:
        # Production mode: use bcrypt hash
        password_valid = verify_password(request.password, admin_pass_hash)
    elif settings.DEV_MODE and admin_pass_plain:
        # Dev mode fallback: plaintext comparison
        password_valid = request.password == admin_pass_plain
    else:
        # Production mode without hash - require hash
        raise HTTPException(status_code=501, detail="Production mode requires API_ADMIN_PASSWORD_HASH. Set DEV_MODE=true for plaintext passwords.")

    if not password_valid:
        log_event("auth_failed", ctx=API_CTX, data={"reason": "invalid_password"})
        raise HTTPException(status_code=401, detail="Invalid credentials")

    log_event("auth_success", ctx=API_CTX, data={"user": request.username})

    token = create_access_token(user_id=request.username, additional_claims={"role": "admin"})
    return TokenResponse(access_token=token, expires_in=JWT_EXPIRATION_HOURS * 3600)


@app.get("/api/auth/me")
async def get_current_user(user: dict = Depends(require_auth)):
    """Get current authenticated user info."""
    return {
        "user_id": user.get("sub"),
        "role": user.get("role", "user"),
    }


@app.get("/api/pending-approvals")
async def get_pending_approvals(user: dict = Depends(require_auth)):
    """
    Return list of trades awaiting manual approval.
    """
    return global_container.execution_store.list_pending()


class ApprovalRequest(BaseModel):
    request_id: str
    confirm_token: str
    approve: bool


_approval_lock = asyncio.Lock()


@app.post("/api/approve-trade")
async def approve_trade(req: ApprovalRequest, user: dict = Depends(require_auth)):
    """
    Approve or cancel a pending trade proposal.

    This endpoint enforces atomic execution - a proposal can only be executed once.
    """
    log_event(
        "trade_approval_request",
        ctx=API_CTX,
        data={
            "user": user.get("sub"),
            "request_id": req.request_id,
            "approve": req.approve,
        },
    )
    try:
        if req.approve:
            prop = global_container.execution_store.confirm(req.request_id, req.confirm_token)

            # Check if already executed (atomic execution guarantee)
            if hasattr(prop, "executed") and prop.executed:
                return JSONResponse(
                    status_code=409,
                    content=json_error_response(
                        ReadyTraderError(code="EXEC_308", message=f"Proposal {req.request_id} has already been executed", data={"request_id": req.request_id})
                    ),
                )

            # Avoid re-proposing while executing an already-approved action.
            async with _approval_lock:
                old_mode = settings.EXECUTION_APPROVAL_MODE
                try:
                    set_execution_approval_mode("auto")
                    payload = dict(prop.payload or {})
                    idem = (payload.get("idempotency_key") or "").strip() or prop.request_id

                    if prop.kind == "swap_tokens":
                        res = swap_tokens(
                            from_token=str(payload["from_token"]),
                            to_token=str(payload["to_token"]),
                            amount=float(payload["amount"]),
                            chain=str(payload.get("chain") or "ethereum"),
                            rationale=str(payload.get("rationale") or ""),
                            idempotency_key=idem,
                        )
                    elif prop.kind == "transfer_eth":
                        res = transfer_eth(
                            to_address=str(payload["to_address"]),
                            amount=float(payload["amount"]),
                            chain=str(payload.get("chain") or "ethereum"),
                            idempotency_key=idem,
                        )
                    elif prop.kind == "place_cex_order":
                        res = place_cex_order(
                            symbol=str(payload["symbol"]),
                            side=str(payload["side"]),
                            amount=float(payload["amount"]),
                            order_type=str(payload.get("order_type") or "market"),
                            price=float(payload["price"]) if payload.get("price") is not None else None,
                            exchange=str(payload.get("exchange") or "binance"),
                            market_type=str(payload.get("market_type") or "spot"),
                            idempotency_key=idem,
                        )
                    else:
                        raise HTTPException(status_code=400, detail=f"Unknown proposal kind: {prop.kind}")

                    # Mark proposal as executed to prevent double-execution
                    global_container.execution_store.mark_executed(req.request_id)

                    # Tool functions return JSON strings; convert to object for API output.
                    return json.loads(res)
                finally:
                    set_execution_approval_mode(old_mode.value if hasattr(old_mode, "value") else str(old_mode))
        else:
            success = global_container.execution_store.cancel(req.request_id)
            return {"ok": success}
    except ReadyTraderError as e:
        log_event("trade_approval_error", ctx=API_CTX, data={"error": e.to_dict()})
        return JSONResponse(status_code=400, content=json_error_response(e))
    except Exception as e:
        log_event("trade_approval_error", ctx=API_CTX, data={"error": str(e)})
        error = InternalError(component="approve_trade", reason="unexpected internal failure")
        return JSONResponse(status_code=500, content=json_error_response(error))


@app.get("/api/portfolio")
async def get_portfolio(user: dict = Depends(require_auth)):
    """
    Get current portfolio state (paper or live).
    """
    if settings.PAPER_MODE:
        balances = global_container.paper_engine.get_balances("agent_zero")
        pnl = global_container.paper_engine.get_risk_metrics("agent_zero")
        return {"balances": balances, "metrics": pnl}
    else:
        out = {
            "mode": "live",
            "ts": time.time(),
            "wallet": {"address": global_container.signer.get_address()},
            "onchain": {},
            "cex": {},
        }

        # On-chain native balances (best-effort)
        chains = [c.strip() for c in (os.getenv("PORTFOLIO_CHAINS") or "ethereum").split(",") if c.strip()]
        for chain in chains:
            try:
                w3 = get_web3(chain)
                addr = w3.to_checksum_address(out["wallet"]["address"])
                bal = int(w3.eth.get_balance(addr))
                out["onchain"][chain] = {"native_balance_wei": bal}
            except Exception as e:
                out["onchain"][chain] = {"error": str(e)}

        # CEX balances (best-effort; only for exchanges with creds)
        exchanges = [e.strip() for e in (os.getenv("PORTFOLIO_EXCHANGES") or "binance").split(",") if e.strip()]
        for ex_id in exchanges:
            try:
                ex = CexExecutor(exchange_id=ex_id, market_type="spot", auth=True)
                out["cex"][ex_id] = {"balance": ex.fetch_balance()}
            except Exception as e:
                out["cex"][ex_id] = {"error": str(e)}

        return out


# -----------------------------------------------------------------------------
# Metrics and Admin Endpoints
# -----------------------------------------------------------------------------
@app.get("/api/metrics")
async def get_metrics(user: dict = Depends(require_auth)):
    """Get system metrics snapshot."""
    return global_container.metrics.snapshot()


@app.get("/api/marketdata/status")
async def get_marketdata_status(user: dict = Depends(require_auth)):
    """Get market data provider status."""
    return global_container.marketdata_bus.status()


@app.get("/api/audit/export")
async def export_audit_log(user: dict = Depends(require_admin)):
    """Export audit log as CSV for compliance."""
    from starlette.responses import Response

    csv_content = global_container.audit_log.export_tax_report()
    return Response(content=csv_content, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=audit_export.csv"})


@app.get("/api/strategies")
async def list_strategies(user: dict = Depends(require_auth), limit: int = 20):
    """List registered strategies from the marketplace."""
    strategies = global_container.strategy_registry.list_strategies(limit=limit)
    return {"strategies": [vars(s) for s in strategies]}


@app.get("/api/insights")
async def list_insights(user: dict = Depends(require_auth), symbol: str = "", limit: int = 10):
    """List recent market insights."""
    insights = global_container.insight_store.get_latest_insights(symbol=symbol if symbol else None, limit=limit)
    return {"insights": [vars(i) for i in insights]}


# -----------------------------------------------------------------------------
# Trade History Endpoint
# -----------------------------------------------------------------------------
@app.get("/api/trades/history")
async def get_trade_history(user: dict = Depends(require_auth), limit: int = 50):
    """Get recent trade history from paper engine or audit log."""
    if settings.PAPER_MODE and global_container.paper_engine:
        # Return paper trades
        import sqlite3

        conn = sqlite3.connect(global_container.paper_engine.db_path)
        cursor = conn.execute(
            """
            SELECT id, timestamp, side, symbol, amount, price, total_value, rationale
            FROM orders
            WHERE user_id = 'agent_zero'
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        )
        trades = []
        for row in cursor:
            trades.append(
                {
                    "id": row[0],
                    "timestamp": row[1],
                    "side": row[2],
                    "symbol": row[3],
                    "amount": row[4],
                    "price": row[5],
                    "total_value": row[6],
                    "rationale": row[7],
                }
            )
        conn.close()
        return {"trades": trades, "mode": "paper"}

    return {"trades": [], "mode": "live", "note": "Live trade history available via audit log export"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("API_PORT", 8000))
    host = os.getenv("API_HOST", "127.0.0.1")
    log_event("api_server_started", ctx=API_CTX, data={"port": port, "host": host})
    uvicorn.run(app, host=host, port=port)
