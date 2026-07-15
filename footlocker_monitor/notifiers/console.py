"""Prints restock alerts to stdout (always-on default)."""

from __future__ import annotations

from .base import Notifier
from ..state import RestockEvent


class ConsoleNotifier(Notifier):
    def notify(self, event: RestockEvent) -> None:
        print("\n" + "=" * 60)
        print(self.format_title(event))
        print("-" * 60)
        print(self.format_body(event))
        print("=" * 60 + "\n", flush=True)
