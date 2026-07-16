"""Vercel Cron function: runs ONE restock sweep per invocation.

Vercel calls this on the schedule in vercel.json. It fetches each watched
product, compares against the last-known stock stored in Upstash Redis, sends a
Discord alert on any restock, and writes the new state + a dashboard payload
back to Redis (which /api/status then serves).

Required environment variables (set them in the Vercel project settings):
  UPSTASH_REDIS_REST_URL, UPSTASH_REDIS_REST_TOKEN   Upstash Redis (free tier)
  DISCORD_WEBHOOK_URL                                 where alerts go
  WATCH_JSON                                          JSON array of products to watch
Optional:
  PROXY_URL          https proxy, to get past Foot Locker's Akamai edge
  CRON_SECRET        Vercel sets this; we reject calls without it
  ALERT_ON_FIRST_SEEN=1   also alert for items already in stock on the first run
"""

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler

# Make the repo-root package importable from within /api.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from footlocker_monitor.notifiers.discord import DiscordNotifier  # noqa: E402
from footlocker_monitor.product import WatchedProduct  # noqa: E402
from footlocker_monitor.scraper import Scraper  # noqa: E402
from footlocker_monitor.serverless import UpstashRedis, run_sweep  # noqa: E402

STATE_KEY = "footlocker:state"
STATUS_KEY = "footlocker:status"
EVENTS_KEY = "footlocker:events"


def _load_watch() -> list:
    raw = os.environ.get("WATCH_JSON")
    if not raw:
        # Fall back to a committed watchlist.json at the repo root, if present.
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "watchlist.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                raw = fh.read()
    if not raw:
        return []
    entries = json.loads(raw)
    return [WatchedProduct.from_config(e) for e in entries]


def run() -> dict:
    redis = UpstashRedis.from_env(os.environ)
    if not redis:
        return {"ok": False, "error": "Upstash Redis env vars not set"}

    watch = _load_watch()
    if not watch:
        return {"ok": False, "error": "no products to watch (set WATCH_JSON)"}

    proxy = os.environ.get("PROXY_URL")
    scraper = Scraper(
        proxies={"https": proxy, "http": proxy} if proxy else None,
        max_retries=1,          # keep within the function's time budget
    )

    notifiers = []
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if webhook:
        notifiers.append(DiscordNotifier(webhook_url=webhook))

    prev_state = redis.get_json(STATE_KEY) or {}
    result = run_sweep(
        watch, prev_state, scraper, notifiers,
        alert_on_first_seen=os.environ.get("ALERT_ON_FIRST_SEEN") == "1",
    )

    # Persist new state + a dashboard payload + append events to a capped list.
    redis.set_json(STATE_KEY, result.state)

    now = time.time()
    status = result.status
    status["interval_seconds"] = None
    for p in status["products"]:
        if p.get("checked_at") is None and not p.get("pending"):
            p["checked_at"] = now
    prior_events = redis.get_json(EVENTS_KEY) or []
    new_events = []
    for e in result.events:
        d = {"ts": now, "kind": e.kind, "name": e.name, "sku": e.sku, "url": e.url,
             "sizes": e.newly_available_sizes, "price": e.price, "previous_price": e.previous_price}
        new_events.append(d)
    all_events = (new_events + prior_events)[:50]
    status["events"] = all_events
    redis.set_json(EVENTS_KEY, all_events)
    redis.set_json(STATUS_KEY, status)

    return {"ok": True, "checked": len(watch), "alerts": len(result.events)}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Vercel Cron sends Authorization: Bearer $CRON_SECRET when set.
        secret = os.environ.get("CRON_SECRET")
        if secret and self.headers.get("Authorization") != f"Bearer {secret}":
            self._send(401, {"ok": False, "error": "unauthorized"})
            return
        try:
            result = run()
            self._send(200 if result.get("ok") else 500, result)
        except Exception as exc:  # noqa: BLE001
            self._send(500, {"ok": False, "error": str(exc)})

    def _send(self, status: int, data: dict):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)
