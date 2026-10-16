"""Security regressions for live intent, fee limits, and execution replay protection."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import ccxt
import pytest

from execution.cex_executor import CexExecutor
from idempotency_store import IdempotencyStore
from signing.policy import PolicyEnforcedSigner, SignerPolicyViolation, policy_config_from_env


@pytest.mark.parametrize(
    "fees",
    [
        {"type": 2, "maxFeePerGas": 101, "maxPriorityFeePerGas": 1},
        {"type": "0x2", "maxFeePerGas": "0x65", "maxPriorityFeePerGas": "0x1"},
        {"type": 2, "maxFeePerGas": 50, "maxPriorityFeePerGas": 51},
        {"type": 2, "maxFeePerGas": 50},
        {"type": 2, "maxFeePerGas": 50, "maxPriorityFeePerGas": 1, "gasPrice": 1},
        {"gasPrice": True},
        {"gasPrice": -1},
        {"gasPrice": 1.9},
        {"gasPrice": "oops"},
    ],
)
def test_signer_rejects_unsafe_fees_before_signing(monkeypatch, fees):
    monkeypatch.setenv("SIGNER_MAX_GAS_PRICE_WEI", "100")
    signed = []
    signer = PolicyEnforcedSigner(SimpleNamespace(sign_transaction=lambda *a, **kw: signed.append(a)), policy_config_from_env())
    with pytest.raises(SignerPolicyViolation):
        signer.sign_transaction({"to": "0x" + "11" * 20, "value": 0, "gas": 21000, **fees}, chain_id=1)
    assert signed == []


def test_pending_claim_is_atomic_between_store_instances(monkeypatch, tmp_path):
    monkeypatch.setenv("IDEMPOTENCY_DB_PATH", str(tmp_path / "claims.db"))
    stores = [IdempotencyStore(), IdempotencyStore()]
    payload = {"kind": "place_cex_order", "symbol": "BTC/USDT", "amount": 1}
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda s: s.reserve("same-key", payload), stores))
    assert sum(c["acquired"] for c in claims) == 1
    assert {c["state"] for c in claims} == {"pending"}


def test_claim_binds_key_to_payload_even_across_restart(monkeypatch, tmp_path):
    monkeypatch.setenv("IDEMPOTENCY_DB_PATH", str(tmp_path / "claims.db"))
    IdempotencyStore().reserve("trade", {"kind": "cex", "amount": 1})
    with pytest.raises(Exception) as exc:
        IdempotencyStore().reserve("trade", {"kind": "transfer", "amount": 1})
    assert getattr(exc.value, "code", None) == "idempotency_conflict"


class TimeoutExchange:
    id = "binance"
    has = {"fetchOrder": True}

    def __init__(self, *, reconciles):
        self.creates = 0
        self.params = None
        self.reconciles = reconciles

    def load_markets(self):
        return {"BTC/USDT": {"symbol": "BTC/USDT", "spot": True}}

    def create_order(self, symbol, order_type, side, amount, price, params):
        self.creates += 1
        self.params = dict(params)
        raise ccxt.RequestTimeout("response lost after acceptance")

    def fetch_order(self, order_id, symbol, params):
        assert params == {"origClientOrderId": "stable-id"}
        if not self.reconciles:
            raise ccxt.OrderNotFound("not yet visible")
        return {"id": "accepted-once", "clientOrderId": "stable-id", "symbol": symbol, "status": "open"}


@pytest.mark.parametrize("reconciles", [True, False])
def test_create_timeout_never_resubmits_and_reconciles_by_client_id(monkeypatch, reconciles):
    fake = TimeoutExchange(reconciles=reconciles)
    monkeypatch.setattr("execution.cex_executor._get_private_exchange", lambda *a: fake)
    monkeypatch.setattr("execution.retry.time.sleep", lambda _: None)
    executor = CexExecutor("binance")
    if reconciles:
        result = executor.place_order(symbol="BTC/USDT", side="buy", amount=0.01, params={"clientOrderId": "stable-id"})
        assert result["id"] == "accepted-once"
    else:
        with pytest.raises(Exception) as exc:
            executor.place_order(symbol="BTC/USDT", side="buy", amount=0.01, params={"clientOrderId": "stable-id"})
        assert getattr(exc.value, "code", None) == "execution_outcome_uncertain"
    assert fake.creates == 1


def test_expired_claim_never_grants_permission_to_resend(monkeypatch, tmp_path):
    monkeypatch.setenv("IDEMPOTENCY_DB_PATH", str(tmp_path / "claims.db"))
    monkeypatch.setattr("idempotency_store.time.time", lambda: 100)
    payload = {"kind": "cex", "amount": 1}
    first = IdempotencyStore().reserve("trade", payload, lease_seconds=1)
    monkeypatch.setattr("idempotency_store.time.time", lambda: 102)
    second = IdempotencyStore().reserve("trade", payload)
    assert second["acquired"] is False
    assert second["state"] == "uncertain"
    assert second["client_order_id"] == first["client_order_id"]


def test_completed_claim_replays_result_but_not_different_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("IDEMPOTENCY_DB_PATH", str(tmp_path / "claims.db"))
    store = IdempotencyStore()
    payload = {"kind": "cex", "amount": 1}
    claim = store.reserve("trade", payload)
    store.complete("trade", claim["owner"], {"order": {"id": "accepted-once"}})
    replay = IdempotencyStore().reserve("trade", payload)
    assert replay["state"] == "completed"
    assert replay["result"] == {"order": {"id": "accepted-once"}}
    assert replay["acquired"] is False
    with pytest.raises(Exception) as exc:
        store.reserve("trade", {"kind": "cex", "amount": 2})
    assert exc.value.code == "idempotency_conflict"


def test_application_policy_caps_type2_fees(monkeypatch):
    from policy_engine import PolicyEngine, PolicyError

    monkeypatch.setenv("MAX_SIGN_GAS_PRICE_WEI", "100")
    with pytest.raises(PolicyError) as exc:
        PolicyEngine().validate_sign_tx(
            chain_id=1,
            to_address="0x" + "11" * 20,
            value_wei=0,
            gas=21000,
            gas_price_wei=None,
            data_hex="0x",
            max_fee_per_gas_wei=101,
            max_priority_fee_per_gas_wei=1,
            tx_type=2,
        )
    assert exc.value.code == "sign_gas_price_too_large"


@pytest.fixture
def live_execution(monkeypatch, tmp_path):
    import copy

    import app.tools.execution as execution
    from app.core.settings import ApprovalMode, ExecutionMode

    settings = copy.copy(execution.settings)
    for key, value in {
        "PAPER_MODE": False,
        "LIVE_TRADING_ENABLED": True,
        "TRADING_HALTED": False,
        "EXECUTION_MODE": ExecutionMode.HYBRID,
        "EXECUTION_APPROVAL_MODE": ApprovalMode.AUTO,
    }.items():
        object.__setattr__(settings, key, value)
    monkeypatch.setattr(execution, "settings", settings)
    monkeypatch.setattr(execution, "pre_trade_check", lambda *a, **kw: {"allowed": True})
    monkeypatch.setattr(execution, "swap_check", lambda *a, **kw: {"allowed": True})
    monkeypatch.setenv("IDEMPOTENCY_DB_PATH", str(tmp_path / "live-claims.db"))
    monkeypatch.setattr(execution.global_container, "idempotency_store", IdempotencyStore())
    monkeypatch.setattr(execution.global_container, "audit_log", SimpleNamespace(append=lambda **kw: None))
    return execution


@pytest.mark.parametrize("selector", ["0x12aa3caf", "0x0502b1c5", "0xdeadbeef", "0x"])
def test_opaque_dex_calldata_cannot_be_signed_or_proposed(live_execution, monkeypatch, selector):
    import json

    execution = live_execution
    signed = []
    broadcasts = []
    monkeypatch.setattr(
        execution.global_container,
        "signer",
        SimpleNamespace(
            get_address=lambda: "0x" + "11" * 20,
            sign_transaction=lambda *a, **kw: signed.append(a) or SimpleNamespace(rawTransaction=b"signed"),
        ),
    )
    monkeypatch.setattr(
        execution.global_container.dex_handler,
        "build_swap_tx",
        lambda *a, **kw: {"tx": {"to": "0x" + "22" * 20, "data": selector, "value": 0, "gas": 21000, "gasPrice": 1}},
    )
    monkeypatch.setattr(execution, "erc20_decimals", lambda *a: 6, raising=False)
    monkeypatch.setattr(execution, "get_web3", lambda *a: SimpleNamespace(eth=SimpleNamespace(get_transaction_count=lambda *a: 0)))
    monkeypatch.setattr(execution, "send_raw_transaction", lambda *a: broadcasts.append(a) or "0xhash")
    result = json.loads(execution.swap_tokens("USDC", "WETH", 1, idempotency_key="swap"))
    assert result["ok"] is False
    assert result["error"]["code"] == "unsupported_swap_semantics"
    assert signed == [] and broadcasts == []


def test_dex_builder_refuses_unverifiable_aggregation_without_contacting_provider(monkeypatch):
    from dex_handler import DexHandler

    contacted = []
    monkeypatch.setenv("ONEINCH_API_KEY", "test-only")
    monkeypatch.setattr("dex_handler.requests.get", lambda *a, **kw: contacted.append(a))
    result = DexHandler().build_swap_tx("ethereum", "USDC", "WETH", "1", "0x" + "11" * 20)
    assert result.get("code") == "unsupported_swap_semantics"
    assert contacted == []


def test_live_order_requires_a_durable_key_before_exchange_effect(live_execution, monkeypatch):
    import json

    creates = []
    monkeypatch.setattr(
        live_execution, "CexExecutor", lambda **kw: SimpleNamespace(place_order=lambda **kw: creates.append(kw) or {"id": "order"}, normalize_order=lambda o: o)
    )
    result = json.loads(live_execution.place_cex_order("BTC/USDT", "buy", 0.01))
    assert result["ok"] is False
    assert result["error"]["code"] == "idempotency_key_required"
    assert creates == []


def test_live_order_claim_precedes_effect_and_survives_audit_failure(live_execution, monkeypatch):
    import json

    execution = live_execution
    creates = []
    payload = {
        "kind": "place_cex_order",
        "exchange": "binance",
        "market_type": "spot",
        "symbol": "BTC/USDT",
        "side": "buy",
        "amount": 0.01,
        "order_type": "market",
        "price": None,
    }

    def create(**kw):
        observed = IdempotencyStore().reserve("same-trade", payload)
        assert observed["acquired"] is False
        assert observed["state"] == "pending"
        assert observed["client_order_id"] == kw["params"]["clientOrderId"]
        creates.append(kw)
        return {"id": "accepted-once"}

    monkeypatch.setattr(execution, "CexExecutor", lambda **kw: SimpleNamespace(place_order=create, normalize_order=lambda o: o))

    def audit_failure(**kw):
        raise OSError("disk unavailable")

    monkeypatch.setattr(execution.global_container, "audit_log", SimpleNamespace(append=audit_failure))
    first = json.loads(execution.place_cex_order("BTC/USDT", "buy", 0.01, idempotency_key="same-trade"))
    second = json.loads(execution.place_cex_order("BTC/USDT", "buy", 0.01, idempotency_key="same-trade"))
    assert first["ok"] is True and second["ok"] is True
    assert first["data"]["order"]["id"] == second["data"]["order"]["id"] == "accepted-once"
    assert len(creates) == 1


def test_edit_timeout_is_not_retried(monkeypatch):
    fake = TimeoutExchange(reconciles=False)
    fake.has = {"editOrder": True}
    edits = []

    def edit(*args):
        edits.append(args)
        raise ccxt.RequestTimeout("edit response lost")

    fake.edit_order = edit
    monkeypatch.setattr("execution.cex_executor._get_private_exchange", lambda *a: fake)
    monkeypatch.setattr("execution.retry.time.sleep", lambda _: None)
    with pytest.raises(Exception) as exc:
        CexExecutor("binance").replace_order(order_id="old", symbol="BTC/USDT", side="buy", amount=1)
    assert exc.value.code == "execution_outcome_uncertain"
    assert len(edits) == 1


def test_claim_is_atomic_across_processes(monkeypatch, tmp_path):
    import json
    import subprocess
    import sys

    monkeypatch.setenv("IDEMPOTENCY_DB_PATH", str(tmp_path / "process-claims.db"))
    script = 'import json; from idempotency_store import IdempotencyStore; print(json.dumps(IdempotencyStore().reserve("one-effect", {"amount": 1})))'
    workers = [subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    results = []
    for worker in workers:
        out, err = worker.communicate(timeout=20)
        assert worker.returncode == 0, err
        results.append(json.loads(out))
    assert sum(r["acquired"] for r in results) == 1
    assert results[0]["client_order_id"] == results[1]["client_order_id"]


def test_legacy_unbound_result_never_authorizes_execution(monkeypatch, tmp_path):
    monkeypatch.setenv("IDEMPOTENCY_DB_PATH", str(tmp_path / "legacy.db"))
    store = IdempotencyStore()
    store.set("legacy-key", {"tx_hash": "old-effect"})
    with pytest.raises(Exception) as exc:
        IdempotencyStore().reserve("legacy-key", {"kind": "transfer_eth", "amount": 5})
    assert exc.value.code == "idempotency_legacy_record"


def test_replace_requires_key_before_edit(live_execution, monkeypatch):
    import json

    edits = []
    monkeypatch.setattr(
        live_execution,
        "CexExecutor",
        lambda **kw: SimpleNamespace(replace_order=lambda **kw: edits.append(kw) or {"id": "edited"}, normalize_order=lambda o: o),
    )
    result = json.loads(live_execution.replace_cex_order("binance", "old", "BTC/USDT", "buy", 0.01, price=100))
    assert result["ok"] is False
    assert result["error"]["code"] == "idempotency_key_required"
    assert edits == []


def test_replace_replays_durable_result_without_second_edit(live_execution, monkeypatch):
    import json

    edits = []

    def edit(**kw):
        edits.append(kw)
        return {"id": "edited"}

    monkeypatch.setattr(live_execution, "CexExecutor", lambda **kw: SimpleNamespace(replace_order=edit, normalize_order=lambda o: o))
    first = json.loads(live_execution.replace_cex_order("binance", "old", "BTC/USDT", "buy", 0.01, price=100, idempotency_key="edit-key"))
    second = json.loads(live_execution.replace_cex_order("binance", "old", "BTC/USDT", "buy", 0.01, price=100, idempotency_key="edit-key"))
    assert first["ok"] is True and second == first
    assert len(edits) == 1


def test_native_timeout_records_broadcast_identity_and_never_resends(live_execution, monkeypatch):
    import json

    execution = live_execution
    wallet, recipient = "0x" + "11" * 20, "0x" + "22" * 20
    sends, signs = [], []

    def nonce(address, block):
        assert address == wallet and block == "pending"
        return 0

    monkeypatch.setattr(
        execution, "get_web3", lambda *a: SimpleNamespace(to_checksum_address=lambda a: a, eth=SimpleNamespace(get_transaction_count=nonce, gas_price=1))
    )

    def sign(tx, **kw):
        signs.append(tx)
        return SimpleNamespace(rawTransaction=b"signed")

    monkeypatch.setattr(execution.global_container, "signer", SimpleNamespace(get_address=lambda: wallet, sign_transaction=sign))
    payload = {"kind": "transfer_eth", "chain": "ethereum", "to_address": recipient, "amount": 0.01}

    def broadcast(*a):
        observed = IdempotencyStore().reserve("native-key", payload)
        assert observed["acquired"] is False
        assert observed["evidence"]["nonce"] == 0
        assert observed["evidence"]["from_address"] == wallet
        assert observed["evidence"]["tx_hash"].startswith("0x")
        sends.append(a)
        raise TimeoutError("lost send response")

    monkeypatch.setattr(execution, "send_raw_transaction", broadcast)
    first = json.loads(execution.transfer_eth(recipient, 0.01, idempotency_key="native-key"))
    second = json.loads(execution.transfer_eth(recipient, 0.01, idempotency_key="native-key"))
    assert first["error"]["code"] == second["error"]["code"] == "execution_outcome_uncertain"
    assert first["error"]["data"]["evidence"]["tx_hash"] == second["error"]["data"]["evidence"]["tx_hash"]
    assert len(sends) == len(signs) == 1


def test_native_transfer_requires_key_before_signing(live_execution, monkeypatch):
    import json

    signs = []
    monkeypatch.setattr(live_execution.global_container, "signer", SimpleNamespace(sign_transaction=lambda *a, **kw: signs.append(a)))
    result = json.loads(live_execution.transfer_eth("0x" + "22" * 20, 0.01))
    assert result["error"]["code"] == "idempotency_key_required"
    assert signs == []


def test_live_claim_refuses_ephemeral_database(monkeypatch):
    monkeypatch.setenv("READYTRADER_IDEMPOTENCY_DB_PATH", ":memory:")
    with pytest.raises(Exception) as exc:
        IdempotencyStore().reserve("one-effect", {"kind": "transfer_eth", "amount": 1})
    assert exc.value.code == "idempotency_persistence_required"


@pytest.mark.parametrize("kind", ["place_cex_order", "replace_cex_order", "transfer_eth"])
@pytest.mark.parametrize("changed_gate", ["risk", "halt", "approval", "venue"])
def test_completed_live_result_replays_before_changed_gates(live_execution, monkeypatch, kind, changed_gate):
    import json

    from app.core.settings import ApprovalMode, ExecutionMode

    execution = live_execution
    key = "completed-request"
    recipient = "0x" + "22" * 20
    payloads = {
        "place_cex_order": {
            "kind": "place_cex_order",
            "exchange": "binance",
            "market_type": "spot",
            "symbol": "BTC/USDT",
            "side": "buy",
            "amount": 0.01,
            "order_type": "limit",
            "price": 100.0,
        },
        "replace_cex_order": {
            "kind": "replace_cex_order",
            "exchange": "binance",
            "market_type": "spot",
            "order_id": "old",
            "symbol": "BTC/USDT",
            "side": "buy",
            "amount": 0.01,
            "order_type": "limit",
            "price": 100.0,
        },
        "transfer_eth": {"kind": "transfer_eth", "chain": "ethereum", "to_address": recipient, "amount": 0.01},
    }
    result = {"order": {"id": "accepted-once"}} if kind != "transfer_eth" else {"tx_hash": "0xaccepted"}
    store = execution.global_container.idempotency_store
    claim = store.reserve(key, payloads[kind])
    store.complete(key, claim["owner"], result)
    if changed_gate == "risk":
        monkeypatch.setattr(execution, "pre_trade_check", lambda *a, **kw: {"allowed": False, "reason": "account changed"})
        monkeypatch.setenv("MAX_TRANSFER_NATIVE", "0")
    elif changed_gate == "halt":
        object.__setattr__(execution.settings, "TRADING_HALTED", True)
    elif changed_gate == "approval":
        object.__setattr__(execution.settings, "EXECUTION_APPROVAL_MODE", ApprovalMode.APPROVE_EACH)
    else:
        object.__setattr__(execution.settings, "EXECUTION_MODE", ExecutionMode.CEX if kind == "transfer_eth" else ExecutionMode.DEX)
    proposals = []
    monkeypatch.setattr(
        execution.global_container.execution_store,
        "create",
        lambda **kw: proposals.append(kw) or SimpleNamespace(request_id="new-proposal", confirm_token="token", expires_at=999999, kind=kind),
    )
    effects = []
    monkeypatch.setattr(execution, "CexExecutor", lambda **kw: effects.append(kw))
    monkeypatch.setattr(execution, "get_web3", lambda *a: effects.append(a))
    if kind == "place_cex_order":
        raw = execution.place_cex_order("BTC/USDT", "buy", 0.01, "limit", 100, idempotency_key=key)
    elif kind == "replace_cex_order":
        raw = execution.replace_cex_order("binance", "old", "BTC/USDT", "buy", 0.01, price=100, idempotency_key=key)
    else:
        raw = execution.transfer_eth(recipient, 0.01, idempotency_key=key)
    replay = json.loads(raw)
    assert replay["ok"] is True
    assert all(replay["data"][field] == value for field, value in result.items())
    assert proposals == [] and effects == []


@pytest.mark.parametrize("kind", ["place_cex_order", "replace_cex_order", "transfer_eth"])
def test_replay_payload_conflict_is_detected_before_changed_halt(live_execution, kind):
    import json

    execution = live_execution
    claim = execution.global_container.idempotency_store.reserve("conflicting-key", {"kind": kind, "amount": 99})
    execution.global_container.idempotency_store.complete("conflicting-key", claim["owner"], {"old": "result"})
    object.__setattr__(execution.settings, "TRADING_HALTED", True)
    if kind == "place_cex_order":
        raw = execution.place_cex_order("BTC/USDT", "buy", 0.01, idempotency_key="conflicting-key")
    elif kind == "replace_cex_order":
        raw = execution.replace_cex_order("binance", "old", "BTC/USDT", "buy", 0.01, price=100, idempotency_key="conflicting-key")
    else:
        raw = execution.transfer_eth("0x" + "22" * 20, 0.01, idempotency_key="conflicting-key")
    assert json.loads(raw)["error"]["code"] == "idempotency_conflict"


def test_existing_claim_lookup_never_reserves_missing_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("IDEMPOTENCY_DB_PATH", str(tmp_path / "lookup.db"))
    store = IdempotencyStore()
    payload = {"kind": "place_cex_order", "amount": 1}
    assert store.lookup("not-sent", payload) is None
    assert not (tmp_path / "lookup.db").exists()
    assert store.reserve("not-sent", payload)["acquired"] is True


@pytest.mark.parametrize("state", ["pending", "uncertain"])
@pytest.mark.parametrize("kind", ["place_cex_order", "replace_cex_order", "transfer_eth"])
def test_incomplete_replay_is_not_hidden_by_halt_or_new_approval(live_execution, kind, state):
    import json

    from app.core.settings import ApprovalMode

    execution = live_execution
    recipient = "0x" + "22" * 20
    payloads = {
        "place_cex_order": {
            "kind": "place_cex_order",
            "exchange": "binance",
            "market_type": "spot",
            "symbol": "BTC/USDT",
            "side": "buy",
            "amount": 0.01,
            "order_type": "limit",
            "price": 100.0,
        },
        "replace_cex_order": {
            "kind": "replace_cex_order",
            "exchange": "binance",
            "market_type": "spot",
            "order_id": "old",
            "symbol": "BTC/USDT",
            "side": "buy",
            "amount": 0.01,
            "order_type": "limit",
            "price": 100.0,
        },
        "transfer_eth": {"kind": "transfer_eth", "chain": "ethereum", "to_address": recipient, "amount": 0.01},
    }
    store = execution.global_container.idempotency_store
    claim = store.reserve("incomplete-key", payloads[kind])
    if state == "uncertain":
        store.mark_uncertain("incomplete-key", claim["owner"])
    object.__setattr__(execution.settings, "TRADING_HALTED", True)
    object.__setattr__(execution.settings, "EXECUTION_APPROVAL_MODE", ApprovalMode.APPROVE_EACH)
    if kind == "place_cex_order":
        raw = execution.place_cex_order("BTC/USDT", "buy", 0.01, "limit", 100, idempotency_key="incomplete-key")
    elif kind == "replace_cex_order":
        raw = execution.replace_cex_order("binance", "old", "BTC/USDT", "buy", 0.01, price=100, idempotency_key="incomplete-key")
    else:
        raw = execution.transfer_eth(recipient, 0.01, idempotency_key="incomplete-key")
    result = json.loads(raw)
    assert result["error"]["code"] == ("execution_pending" if state == "pending" else "execution_outcome_uncertain")
    assert result["error"]["data"]["client_order_id"] == claim["client_order_id"]
