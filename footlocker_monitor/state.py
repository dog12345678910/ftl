"""Persistent state so the monitor only alerts on *changes* (restocks)."""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from typing import Optional

from .product import ProductStatus, WatchedProduct, parse_price


@dataclass
class RestockEvent:
    """Emitted when a watched product changes in a way the user cares about.

    ``kind`` is one of ``"restock"`` (out-of-stock -> in-stock), ``"in_stock"``
    (already available on first sighting), or ``"price_drop"``.
    """

    sku: str
    name: str
    url: str
    newly_available_sizes: list[str]
    price: Optional[str] = None
    image: Optional[str] = None
    first_seen: bool = False
    kind: str = "restock"
    previous_price: Optional[str] = None


class StateStore:
    """Tracks the last-known availability per product on disk.

    A restock is a transition ``out-of-stock -> in-stock``. On the very first
    run there's no prior state, so anything already in stock is reported with
    ``first_seen=True`` (callers can choose to suppress those).
    """

    def __init__(self, path: Optional[str] = None, track_price_drops: bool = False) -> None:
        # path=None means "no local persistence" — used on serverless where
        # state lives in an external store (e.g. Redis); load _data yourself.
        self.path = path
        self.track_price_drops = track_price_drops
        self._data: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        if not self.path or not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def load_data(self, data: dict) -> None:
        """Seed state from an external source (e.g. Redis) instead of a file."""
        self._data = dict(data or {})

    def save(self) -> None:
        if not self.path:
            return  # no-persistence mode; caller stores _data elsewhere
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

    def snapshot(self) -> list[dict]:
        """Current per-product state, newest-checked first — for the dashboard."""
        rows = []
        for sku, entry in self._data.items():
            sizes = entry.get("sizes", {})
            rows.append({
                "sku": sku,
                "name": entry.get("name", sku),
                "url": entry.get("url", ""),
                "retailer": entry.get("retailer", ""),
                "in_stock": entry.get("in_stock", False),
                "available_sizes": [s for s, ok in sizes.items() if ok],
                "price": entry.get("price"),
                "checked_at": entry.get("checked_at"),
                "error": entry.get("error"),
            })
        rows.sort(key=lambda r: r.get("checked_at") or 0, reverse=True)
        return rows

    def evaluate(
        self, watched: WatchedProduct, status: ProductStatus
    ) -> Optional[RestockEvent]:
        """Compare ``status`` against stored state and return a RestockEvent
        if something the user cares about just came into stock."""
        now = time.time()
        if status.error:
            # Record that we checked (and why it failed) without clobbering the
            # last-known-good availability, then bail — no alert on failures.
            entry = self._data.get(status.sku, {})
            entry.setdefault("name", status.name)
            entry.setdefault("url", status.url)
            entry.setdefault("retailer", watched.retailer)
            entry["checked_at"] = now
            entry["error"] = status.error
            self._data[status.sku] = entry
            return None

        prev = self._data.get(status.sku)
        first_seen = prev is None
        prev_sizes: dict[str, bool] = (prev or {}).get("sizes", {})
        prev_in_stock: bool = (prev or {}).get("in_stock", False)
        prev_price: Optional[str] = (prev or {}).get("price")

        newly_available: list[str] = []
        if status.sizes:
            for s in status.sizes:
                if not s.in_stock or not watched.wants_size(s.size):
                    continue
                was_in_stock = prev_sizes.get(s.size, False)
                if not was_in_stock:
                    newly_available.append(s.size)
            restocked = bool(newly_available)
        else:
            # No size granularity: trigger on product-level OOS -> in-stock.
            restocked = status.in_stock and not prev_in_stock

        price_drop = self._detect_price_drop(watched, status, prev_price, first_seen)

        # Record the new state regardless of whether we alert.
        self._data[status.sku] = {
            "in_stock": status.in_stock,
            "sizes": status.size_state(),
            "name": status.name,
            "price": status.price,
            "url": status.url,
            "retailer": watched.retailer,
            "checked_at": now,
            "error": None,
        }

        if restocked:
            return RestockEvent(
                sku=status.sku,
                name=status.name,
                url=status.url,
                newly_available_sizes=newly_available or status.available_sizes,
                price=status.price,
                image=status.image,
                first_seen=first_seen,
                kind="in_stock" if first_seen else "restock",
                previous_price=prev_price,
            )

        if price_drop:
            return RestockEvent(
                sku=status.sku,
                name=status.name,
                url=status.url,
                newly_available_sizes=status.available_sizes,
                price=status.price,
                image=status.image,
                first_seen=False,
                kind="price_drop",
                previous_price=prev_price,
            )

        return None

    def _detect_price_drop(
        self,
        watched: WatchedProduct,
        status: ProductStatus,
        prev_price: Optional[str],
        first_seen: bool,
    ) -> bool:
        """A price drop is a fall vs the last-seen price, or crossing a
        configured ``target_price`` for the first time."""
        if not self.track_price_drops:
            return False
        current = parse_price(status.price)
        if current is None:
            return False

        # Target-price crossing: alert once when at/under target and we
        # weren't already under it last time.
        if watched.target_price is not None and current <= watched.target_price:
            previous = parse_price(prev_price)
            if previous is None or previous > watched.target_price:
                return True

        if first_seen:
            return False  # no baseline to compare against yet

        previous = parse_price(prev_price)
        return previous is not None and current < previous
