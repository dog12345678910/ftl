"""Sends restock alerts as SMS text messages via Twilio."""

from __future__ import annotations

import logging

import requests

from .base import Notifier
from ..state import RestockEvent

log = logging.getLogger(__name__)


class TwilioSMSNotifier(Notifier):
    """Delivers alerts by SMS using Twilio's REST API (no SDK required).

    Get ``account_sid`` and ``auth_token`` from the Twilio console, buy/verify
    a ``from_number`` (E.164, e.g. ``+15005550006``), and set ``to`` to your
    phone number (or a list of numbers).
    """

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        from_number: str,
        to: str | list[str],
        timeout: float = 15.0,
    ) -> None:
        if not (account_sid and auth_token and from_number and to):
            raise ValueError(
                "sms notifier requires 'account_sid', 'auth_token', "
                "'from_number' and 'to'"
            )
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self.recipients = [to] if isinstance(to, str) else list(to)
        self.timeout = timeout
        self.endpoint = (
            f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        )

    def notify(self, event: RestockEvent) -> None:
        # SMS is short; lead with the title, then sizes/price, then link.
        body = f"{self.format_title(event)}\n{self.format_body(event)}"
        for number in self.recipients:
            try:
                resp = requests.post(
                    self.endpoint,
                    data={"From": self.from_number, "To": number, "Body": body},
                    auth=(self.account_sid, self.auth_token),
                    timeout=self.timeout,
                )
                if resp.status_code >= 400:
                    log.warning(
                        "Twilio returned HTTP %s for %s: %s",
                        resp.status_code, number, resp.text[:200],
                    )
            except requests.RequestException as exc:
                log.warning("Failed to send SMS to %s: %s", number, exc)
