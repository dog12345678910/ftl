"""Sends restock alerts to a Telegram chat via a bot token."""

from __future__ import annotations

import logging

import requests

from .base import Notifier
from ..state import RestockEvent

log = logging.getLogger(__name__)


class TelegramNotifier(Notifier):
    """Delivers alerts through the Telegram Bot API.

    Create a bot with @BotFather to get ``bot_token``, then message it and
    read your ``chat_id`` from https://api.telegram.org/bot<token>/getUpdates.
    """

    def __init__(self, bot_token: str, chat_id: str, timeout: float = 10.0) -> None:
        if not bot_token or not chat_id:
            raise ValueError("telegram notifier requires 'bot_token' and 'chat_id'")
        self.bot_token = bot_token
        self.chat_id = str(chat_id)
        self.timeout = timeout

    def notify(self, event: RestockEvent) -> None:
        text = f"*{self.format_title(event)}*\n{self.format_body(event)}"
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
        }
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout)
            if resp.status_code >= 400:
                log.warning("Telegram API returned HTTP %s: %s", resp.status_code, resp.text[:200])
        except requests.RequestException as exc:
            log.warning("Failed to send Telegram notification: %s", exc)
