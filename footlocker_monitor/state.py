"""Persistent state so the monitor only alerts on *changes* (restocks)."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from typing import Optional

from .product import ProductStatus, WatchedProduct


@dataclass
class RestockEvent:
    """Emitted when a watched product/size transitions into stock."""

    sku: str
    name: str
    url: str
    newly_available_sizes: list[str]
    price: Optional[str] = None
    image: Optional[str] = None
    first_seen: bool = False


class StateStore:
    """Tracks the last-known availability per product on disk.

    A restock is a transition ``out-of-stock -> in-stock``. On the very first
    run there's no prior state, so anything already in stock is reported with
    ``first_seen=True`` (callers can choose to suppress those).
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._data: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def save(self) -> None:
        directory = os.path.dirname(os.path.abspath(self.path)) or "."
        os.makedirs(directory, exist_ok=True)
        # Atomic write so a crash can't corrupt the state file.
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    def evaluate(
        self, watched: WatchedProduct, status: ProductStatus
    ) -> Optional[RestockEvent]:
        """Compare ``status`` against stored state and return a RestockEvent
        if something the user cares about just came into stock."""
        if status.error:
            return None  # Don't overwrite good state on a transient failure.

        prev = self._data.get(status.sku)
        first_seen = prev is None
        prev_sizes: dict[str, bool] = (prev or {}).get("sizes", {})
        prev_in_stock: bool = (prev or {}).get("in_stock", False)

        newly_available: list[str] = []
        if status.sizes:
            for s in status.sizes:
                if not s.in_stock or not watched.wants_size(s.size):
                    continue
                was_in_stock = prev_sizes.get(s.size, False)
                if not was_in_stock:
                    newly_available.append(s.size)
            triggered = bool(newly_available)
        else:
            # No size granularity: trigger on product-level OOS -> in-stock.
            triggered = status.in_stock and not prev_in_stock

        # Record the new state regardless of whether we alert.
        self._data[status.sku] = {
            "in_stock": status.in_stock,
            "sizes": status.size_state(),
            "name": status.name,
        }

        if not triggered:
            return None

        return RestockEvent(
            sku=status.sku,
            name=status.name,
            url=status.url,
            newly_available_sizes=newly_available or status.available_sizes,
            price=status.price,
            image=status.image,
            first_seen=first_seen,
        )
