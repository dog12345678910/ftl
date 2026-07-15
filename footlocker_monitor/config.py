"""Loads and validates the monitor configuration."""

from __future__ import annotations

import json
import os
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

    # Active-hours window (24h clock, local time). None = run 24/7.
    active_start_hour: int | None = None   # e.g. 8  -> start monitoring at 08:00
    active_end_hour: int | None = None     # e.g. 23 -> stop  monitoring at 23:00

    # Network
    proxies: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    pdp_template: str = "https://www.footlocker.com/api/products/pdp/{sku}"
    timeout: float = 15.0
    max_retries: int = 3

    state_file: str = "monitor_state.json"

    @classmethod
    def load(cls, path: str) -> "Config":
        if not os.path.exists(path):
            raise FileNotFoundError(f"config file not found: {path}")
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Config":
        watch_raw = raw.get("watch") or []
        if not watch_raw:
            raise ValueError("config must define a non-empty 'watch' list")
        watch = [WatchedProduct.from_config(entry) for entry in watch_raw]

        notifiers = raw.get("notifiers") or [{"type": "console"}]

        known = {
            "interval_seconds", "jitter_seconds", "per_product_delay",
            "alert_on_first_seen", "active_start_hour", "active_end_hour",
            "proxies", "cookies", "headers", "pdp_template", "timeout",
            "max_retries", "state_file",
        }
        kwargs = {k: raw[k] for k in known if k in raw}
        return cls(watch=watch, notifiers=notifiers, **kwargs)
