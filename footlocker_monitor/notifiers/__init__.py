"""Notification backends for restock alerts."""

from __future__ import annotations

from typing import Any

from .base import Notifier
from .console import ConsoleNotifier
from .desktop import DesktopNotifier
from .discord import DiscordNotifier
from .email import EmailNotifier
from .telegram import TelegramNotifier
from .webhook import SlackNotifier, WebhookNotifier

_REGISTRY: dict[str, type[Notifier]] = {
    "console": ConsoleNotifier,
    "desktop": DesktopNotifier,
    "discord": DiscordNotifier,
    "email": EmailNotifier,
    "slack": SlackNotifier,
    "telegram": TelegramNotifier,
    "webhook": WebhookNotifier,
}


def build_notifiers(config: list[dict[str, Any]]) -> list[Notifier]:
    """Instantiate notifiers from a list of ``{"type": ..., ...}`` dicts."""
    notifiers: list[Notifier] = []
    for entry in config:
        kind = str(entry.get("type", "")).strip().lower()
        if kind not in _REGISTRY:
            raise ValueError(
                f"unknown notifier type {kind!r}; "
                f"available: {', '.join(sorted(_REGISTRY))}"
            )
        options = {k: v for k, v in entry.items() if k != "type"}
        notifiers.append(_REGISTRY[kind](**options))
    return notifiers


__all__ = [
    "Notifier",
    "ConsoleNotifier",
    "DesktopNotifier",
    "DiscordNotifier",
    "EmailNotifier",
    "SlackNotifier",
    "TelegramNotifier",
    "WebhookNotifier",
    "build_notifiers",
]
