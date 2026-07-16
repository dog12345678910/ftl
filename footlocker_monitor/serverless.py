"""Stateless monitoring sweep for serverless/cron environments (e.g. Vercel).

A normal deployment runs :class:`Monitor` as a long-lived loop with a local
state file. Serverless platforms can't do that — no long-running process, no
persistent disk. This module provides the same restock detection as a single
stateless function whose "memory" lives in an external key-value store (Redis).

Flow per cron invocation:

    prev = redis.get_json("state")            # last-known stock
    result = run_sweep(watch, prev, scraper, notifiers)
    redis.set_json("state", result.state)     # remember for next time
    redis.set_json("status", result.status)   # for the dashboard to read

Notifiers (e.g. Discord) fire on restocks exactly as in the always-on bot.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

import requests

from .notifiers import Notifier
from .product import WatchedProduct
from .retailers import get_retailer
from .state import RestockEvent, StateStore


@dataclass
class SweepResult:
    state: dict            # new state map to persist back to Redis
    events: list[RestockEvent]
    status: dict           # dashboard-ready payload


def run_sweep(
    watch: list[WatchedProduct],
    prev_state: dict,
    scraper,
    notifiers: list[Notifier],
    *,
    alert_on_first_seen: bool = False,
    track_price_drops: bool = False,
) -> SweepResult:
    """Run one sweep over ``watch`` using ``prev_state`` as the baseline."""
    store = StateStore(None, track_price_drops=track_price_drops)
    store.load_data(prev_state)

    events: list[RestockEvent] = []
    for w in watch:
        status = scraper.fetch(w)
        event = store.evaluate(w, status)
        if event and (not event.first_seen or alert_on_first_seen):
            events.append(event)

    for event in events:
        for notifier in notifiers:
            try:
                notifier.notify(event)
            except Exception:  # noqa: BLE001 - one bad channel shouldn't abort
                pass

    return SweepResult(
        state=store._data,
        events=events,
        status=build_status(store, watch, events),
    )


def build_status(store: StateStore, watch: list[WatchedProduct], recent_events) -> dict:
    """Dashboard-ready payload built from an in-memory store (no files)."""
    state_by_sku = {row["sku"]: row for row in store.snapshot()}
    products = []
    for w in watch:
        row = state_by_sku.get(w.sku)
        if row:
            row = dict(row)
            row["pending"] = False
            if not row.get("name"):
                row["name"] = w.name or w.sku
            products.append(row)
        else:
            products.append({
                "sku": w.sku, "name": w.name or w.sku,
                "url": w.url or get_retailer(w.retailer).product_url(w.sku),
                "retailer": w.retailer, "in_stock": False, "available_sizes": [],
                "price": None, "checked_at": None, "error": None, "pending": True,
            })
    events = [_event_to_dict(e) for e in recent_events]
    return {
        "demo": False,
        "products": products,
        "events": events,
        "in_stock_count": sum(1 for p in products if p.get("in_stock")),
        "watched_count": len(watch),
        "interval_seconds": None,
    }


def _event_to_dict(e: RestockEvent) -> dict:
    return {
        "kind": e.kind, "name": e.name, "sku": e.sku, "url": e.url,
        "sizes": e.newly_available_sizes, "price": e.price,
        "previous_price": e.previous_price, "ts": None,
    }


class UpstashRedis:
    """Minimal client for Upstash Redis' REST API (no extra dependencies).

    Create a database at upstash.com (free tier), then set the two env vars it
    gives you: ``UPSTASH_REDIS_REST_URL`` and ``UPSTASH_REDIS_REST_TOKEN``.
    """

    def __init__(self, url: str, token: str, timeout: float = 8.0) -> None:
        self.url = url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}
        self.timeout = timeout

    @classmethod
    def from_env(cls, env: dict) -> Optional["UpstashRedis"]:
        url = env.get("UPSTASH_REDIS_REST_URL") or env.get("KV_REST_API_URL")
        token = env.get("UPSTASH_REDIS_REST_TOKEN") or env.get("KV_REST_API_TOKEN")
        if url and token:
            return cls(url, token)
        return None

    def get_json(self, key: str) -> Any:
        resp = requests.get(f"{self.url}/get/{key}", headers=self.headers, timeout=self.timeout)
        resp.raise_for_status()
        result = resp.json().get("result")
        if not result:
            return None
        try:
            return json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return None

    def set_json(self, key: str, value: Any) -> None:
        resp = requests.post(
            f"{self.url}/set/{key}",
            headers=self.headers,
            data=json.dumps(value),
            timeout=self.timeout,
        )
        resp.raise_for_status()
