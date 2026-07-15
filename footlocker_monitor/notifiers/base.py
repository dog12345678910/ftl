"""Notifier interface and shared message formatting."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..state import RestockEvent


class Notifier(ABC):
    """Base class for all notification backends."""

    @abstractmethod
    def notify(self, event: RestockEvent) -> None:
        """Deliver a restock alert. Implementations should not raise on
        recoverable delivery errors — log and move on."""

    # -- shared helpers -----------------------------------------------------

    @staticmethod
    def format_title(event: RestockEvent) -> str:
        prefix = "👟 IN STOCK" if event.first_seen else "🔔 RESTOCK"
        return f"{prefix}: {event.name}"

    @staticmethod
    def format_body(event: RestockEvent) -> str:
        lines = []
        if event.newly_available_sizes:
            lines.append("Sizes: " + ", ".join(event.newly_available_sizes))
        if event.price:
            lines.append(f"Price: {event.price}")
        lines.append(event.url)
        return "\n".join(lines)
