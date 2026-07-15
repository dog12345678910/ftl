"""Append-only log of alert events, stored as JSON Lines.

Kept separate from the live state file: state answers "is it in stock *now*?",
history answers "what restocked, and when?" — which is what the dashboard's
activity feed shows.
"""

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state import RestockEvent


def append_events(path: str, events: list["RestockEvent"]) -> None:
    if not path or not events:
        return
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    now = time.time()
    with open(path, "a", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps({
                "ts": now,
                "kind": event.kind,
                "sku": event.sku,
                "name": event.name,
                "url": event.url,
                "sizes": event.newly_available_sizes,
                "price": event.price,
                "previous_price": event.previous_price,
            }) + "\n")


def read_recent(path: str, limit: int = 50) -> list[dict]:
    """Return the most recent ``limit`` events, newest first."""
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(out) >= limit:
            break
    return out
