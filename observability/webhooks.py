import json
import logging
import os
import time
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)


class WebhookManager:
    """
    Handles delivery of notifications to external services like Discord and Telegram.
    """

    @staticmethod
    def send_discord_notification(message: str, embed: Optional[Dict[str, Any]] = None):
        webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
        if not webhook_url:
            return

        payload = {"content": message}
        if embed:
            payload["embeds"] = [embed]

        try:
            requests.post(webhook_url, json=payload, timeout=5)
        except Exception as e:
            logger.error(f"Webhook delivery failed to Discord: {type(e).__name__}: {e}")
            # Retry once after 2 seconds
            try:
                time.sleep(2)
                requests.post(webhook_url, json=payload, timeout=5)
            except Exception as retry_err:
                logger.error(f"Webhook retry also failed (Discord): {retry_err}")
                dead_letter_path = os.path.join(os.path.dirname(__file__), "../logs/webhook_dead_letter.jsonl")
                os.makedirs(os.path.dirname(dead_letter_path), exist_ok=True)
                with open(dead_letter_path, "a") as f:
                    f.write(json.dumps({"url": webhook_url, "payload": payload, "error": str(retry_err), "ts": time.time()}) + "\n")

    @staticmethod
    def send_telegram_notification(message: str):
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not bot_token or not chat_id:
            return

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}

        try:
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            logger.error(f"Webhook delivery failed to Telegram: {type(e).__name__}: {e}")
            # Retry once after 2 seconds
            try:
                time.sleep(2)
                requests.post(url, json=payload, timeout=5)
            except Exception as retry_err:
                logger.error(f"Webhook retry also failed (Telegram): {retry_err}")
                dead_letter_path = os.path.join(os.path.dirname(__file__), "../logs/webhook_dead_letter.jsonl")
                os.makedirs(os.path.dirname(dead_letter_path), exist_ok=True)
                with open(dead_letter_path, "a") as f:
                    f.write(json.dumps({"url": url, "payload": payload, "error": str(retry_err), "ts": time.time()}) + "\n")

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
