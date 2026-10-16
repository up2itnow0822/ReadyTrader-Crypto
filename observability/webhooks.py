import json
import logging
import os
import secrets
import threading
import time
from typing import Any, Dict, Optional

import requests

from storage_paths import data_path, ensure_parent

logger = logging.getLogger(__name__)


class WebhookManager:
    """
    Handles delivery of notifications to external services like Discord and Telegram.
    """

    _dead_letter_lock = threading.Lock()

    @classmethod
    def _record_failure(cls, provider: str, correlation_id: str, exc: Exception) -> None:
        # Request exceptions may embed credential-bearing URLs. Never log their text,
        # request/response objects, destination, or message payload.
        error_class = type(exc).__name__
        logger.warning("Webhook delivery failed provider=%s correlation_id=%s error_class=%s", provider, correlation_id, error_class)
        record = {"provider": provider, "correlation_id": correlation_id, "error_class": error_class, "ts": time.time()}
        try:
            with cls._dead_letter_lock:
                path = ensure_parent(data_path("webhook_dead_letter.jsonl"))
                flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
                fd = os.open(path, flags, 0o600)
                with os.fdopen(fd, "a", encoding="utf-8") as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    # Failure storms must not fill the data volume indefinitely.
                    if os.fstat(stream.fileno()).st_size < 1024 * 1024:
                        stream.write(json.dumps(record) + "\n")
        except OSError:
            logger.warning("Webhook failure metadata unavailable correlation_id=%s", correlation_id)

    @classmethod
    def _deliver(cls, provider: str, url: str, payload: Dict[str, Any]) -> None:
        correlation_id = secrets.token_hex(12)
        for attempt in range(2):
            try:
                response = requests.post(url, json=payload, timeout=5)
                response.raise_for_status()
                return
            except requests.RequestException as exc:
                if attempt == 1:
                    cls._record_failure(provider, correlation_id, exc)
                else:
                    time.sleep(2)

    @classmethod
    def send_discord_notification(cls, message: str, embed: Optional[Dict[str, Any]] = None):
        webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
        if not webhook_url:
            return
        payload = {"content": message}
        if embed:
            payload["embeds"] = [embed]
        cls._deliver("discord", webhook_url, payload)

    @classmethod
    def send_telegram_notification(cls, message: str):
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not bot_token or not chat_id:
            return
        cls._deliver("telegram", f"https://api.telegram.org/bot{bot_token}/sendMessage", {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"})

    @classmethod
    def notify_approval_required(cls, kind: str, amount: float, symbol: str, request_id: str):
        """
        Send a notification that a trade requires manual approval.
        """
        msg = f"🛡️ **ReadyTrader: Approval Required**\nKind: {kind}\nAmount: {amount}\nSymbol: {symbol}\nRequest ID: `{request_id}`"

        # Discord Embed
        embed = {
            "title": "Action Required: Trade Approval",
            "color": 0xFFCC00,
            "fields": [
                {"name": "Kind", "value": kind, "inline": True},
                {"name": "Symbol", "value": symbol, "inline": True},
                {"name": "Amount", "value": str(amount), "inline": True},
                {"name": "Request ID", "value": request_id, "inline": False},
            ],
            "footer": {"text": "ReadyTrader-Crypto Guardian Mode"},
        }

        cls.send_discord_notification(msg, embed=embed)
        cls.send_telegram_notification(msg)
