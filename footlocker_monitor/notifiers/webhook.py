"""Generic outgoing-webhook notifiers, including a Slack-formatted variant."""

from __future__ import annotations

import logging

import requests

from .base import Notifier
from ..state import RestockEvent

log = logging.getLogger(__name__)


class WebhookNotifier(Notifier):
    """POSTs a JSON payload describing the alert to any URL.

    The default payload is generic:

        {"kind", "title", "name", "sku", "url", "sizes", "price", "image"}

    Handy for wiring into IFTTT, Zapier, n8n, Home Assistant, or your own
    service. Add ``"headers"`` for auth if the endpoint needs it.
    """

    def __init__(self, url: str, headers: dict | None = None, timeout: float = 10.0) -> None:
        if not url:
            raise ValueError("webhook notifier requires a 'url'")
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout

    def _payload(self, event: RestockEvent) -> dict:
        return {
            "kind": event.kind,
            "title": self.format_title(event),
            "name": event.name,
            "sku": event.sku,
            "url": event.url,
            "sizes": event.newly_available_sizes,
            "price": event.price,
            "previous_price": event.previous_price,
            "image": event.image,
        }

    def notify(self, event: RestockEvent) -> None:
        try:
            resp = requests.post(
                self.url, json=self._payload(event), headers=self.headers, timeout=self.timeout
            )
            if resp.status_code >= 400:
                log.warning("Webhook returned HTTP %s: %s", resp.status_code, resp.text[:200])
        except requests.RequestException as exc:
            log.warning("Failed to send webhook notification: %s", exc)


class SlackNotifier(WebhookNotifier):
    """Posts to a Slack incoming webhook using Slack's message format."""

    def _payload(self, event: RestockEvent) -> dict:
        text = f"*{self.format_title(event)}*\n{self.format_body(event)}"
        return {"text": text}
