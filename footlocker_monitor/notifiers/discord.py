"""Sends restock alerts to a Discord channel via an incoming webhook."""

from __future__ import annotations

import logging

import requests

from .base import Notifier
from ..state import RestockEvent

log = logging.getLogger(__name__)


class DiscordNotifier(Notifier):
    """Posts a rich embed to a Discord webhook URL.

    Create one under Server Settings → Integrations → Webhooks and pass its
    URL as ``webhook_url`` in the notifier config.
    """

    def __init__(self, webhook_url: str, mention: str = "", timeout: float = 10.0) -> None:
        if not webhook_url:
            raise ValueError("discord notifier requires a 'webhook_url'")
        self.webhook_url = webhook_url
        self.mention = mention  # e.g. "@everyone" or "<@USER_ID>"
        self.timeout = timeout

    def notify(self, event: RestockEvent) -> None:
        fields = []
        if event.newly_available_sizes:
            fields.append(
                {"name": "Sizes", "value": ", ".join(event.newly_available_sizes), "inline": True}
            )
        if event.price:
            fields.append({"name": "Price", "value": event.price, "inline": True})

        embed = {
            "title": self.format_title(event),
            "url": event.url,
            "description": event.url,
            "color": 0x2ECC71 if not event.first_seen else 0x3498DB,
            "fields": fields,
        }
        if event.image:
            embed["thumbnail"] = {"url": event.image}

        payload = {"embeds": [embed]}
        if self.mention:
            payload["content"] = self.mention

        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=self.timeout)
            if resp.status_code >= 400:
                log.warning("Discord webhook returned HTTP %s: %s", resp.status_code, resp.text[:200])
        except requests.RequestException as exc:
            log.warning("Failed to send Discord notification: %s", exc)
