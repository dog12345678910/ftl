"""Loads and validates the monitor configuration."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any

from .product import WatchedProduct


@dataclass
class Config:
    watch: list[WatchedProduct]
    notifiers: list[dict[str, Any]] = field(default_factory=lambda: [{"type": "console"}])

    # Polling behaviour
    interval_seconds: int = 90          # base delay between full sweeps
    jitter_seconds: int = 30            # random 0..jitter added to each sleep
    per_product_delay: float = 1.5      # spacing between product requests
    alert_on_first_seen: bool = False   # alert for already-in-stock on run 1?
    track_price_drops: bool = False     # also alert when a price falls?

    # Active-hours window (24h clock, local time). None = run 24/7.
    active_start_hour: int | None = None   # e.g. 8  -> start monitoring at 08:00
    active_end_hour: int | None = None     # e.g. 23 -> stop  monitoring at 23:00

    # Network
    proxies: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    # Empty = use each retailer's own PDP endpoint. Set to override globally.
    pdp_template: str = ""
    timeout: float = 15.0
    max_retries: int = 3

    state_file: str = "monitor_state.json"
    history_file: str = "monitor_history.jsonl"

    @classmethod
    def load(cls, path: str) -> "Config":
        if not os.path.exists(path):
            raise FileNotFoundError(f"config file not found: {path}")
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        return cls.from_dict(raw)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict suitable for writing back to config.json."""
        return {
            "watch": [w.to_dict() for w in self.watch],
            "notifiers": self.notifiers,
            "interval_seconds": self.interval_seconds,
            "jitter_seconds": self.jitter_seconds,
            "per_product_delay": self.per_product_delay,
            "alert_on_first_seen": self.alert_on_first_seen,
            "track_price_drops": self.track_price_drops,
            "active_start_hour": self.active_start_hour,
            "active_end_hour": self.active_end_hour,
            "proxies": self.proxies,
            "cookies": self.cookies,
            "headers": self.headers,
            "pdp_template": self.pdp_template,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "state_file": self.state_file,
            "history_file": self.history_file,
        }

    def save(self, path: str) -> None:
        """Atomically write the config back to ``path`` (used by the UI)."""
        directory = os.path.dirname(os.path.abspath(path)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.to_dict(), fh, indent=2)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Config":
        # An empty watch list is allowed — the dashboard UI can populate it.
        watch_raw = raw.get("watch") or []
        watch = [WatchedProduct.from_config(entry) for entry in watch_raw]

        notifiers = raw.get("notifiers") or [{"type": "console"}]

        known = {
            "interval_seconds", "jitter_seconds", "per_product_delay",
            "alert_on_first_seen", "track_price_drops",
            "active_start_hour", "active_end_hour",
            "proxies", "cookies", "headers", "pdp_template", "timeout",
            "max_retries", "state_file", "history_file",
        }
        kwargs = {k: raw[k] for k in known if k in raw}
        return cls(watch=watch, notifiers=notifiers, **kwargs)
