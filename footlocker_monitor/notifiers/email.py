"""Sends restock alerts by email over SMTP."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from .base import Notifier
from ..state import RestockEvent

log = logging.getLogger(__name__)


class EmailNotifier(Notifier):
    """Delivers alerts via any SMTP server (Gmail, Fastmail, SES, …).

    For Gmail use an app password, host ``smtp.gmail.com`` and port ``587``.
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        to: str | list[str],
        port: int = 587,
        from_addr: str = "",
        use_tls: bool = True,
        timeout: float = 20.0,
    ) -> None:
        if not host or not to:
            raise ValueError("email notifier requires 'host' and 'to'")
        self.host = host
        self.port = int(port)
        self.username = username
        self.password = password
        self.recipients = [to] if isinstance(to, str) else list(to)
        self.from_addr = from_addr or username
        self.use_tls = use_tls
        self.timeout = timeout

    def notify(self, event: RestockEvent) -> None:
        msg = EmailMessage()
        msg["Subject"] = self.format_title(event)
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(self.recipients)
        msg.set_content(self.format_body(event))

        try:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as smtp:
                if self.use_tls:
                    smtp.starttls()
                if self.username:
                    smtp.login(self.username, self.password)
                smtp.send_message(msg)
        except Exception as exc:  # noqa: BLE001 - never kill the loop over one email
            log.warning("Failed to send email notification: %s", exc)
