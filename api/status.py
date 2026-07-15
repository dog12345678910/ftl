"""Vercel serverless function backing the dashboard's /api/status endpoint.

Vercel is serverless, so it cannot run the always-on monitor loop or keep a
persistent state file. This endpoint therefore serves **sample data** by
default so the deployed dashboard renders and you can see the UI.

To show *real* data on Vercel, run the actual monitor somewhere persistent
(your machine, a VPS, Docker — see the repo README) and have it publish its
state JSON somewhere reachable, then set the MONITOR_STATE_URL environment
variable in your Vercel project to that URL. This function will proxy it.
"""

import json
import os
import urllib.request

SAMPLE = {
    "demo": True,
    "watched_count": 4,
    "in_stock_count": 2,
    "interval_seconds": 60,
    "products": [
        {"sku": "314206561604", "name": "Air Jordan 1 Retro High OG 'Chicago'",
         "url": "https://www.footlocker.com/product/~/314206561604.html",
         "retailer": "footlocker", "in_stock": True,
         "available_sizes": ["9", "10", "11.5"], "price": "$180.00",
         "checked_at": None, "error": None},
        {"sku": "316153042104", "name": "Nike Dunk Low 'Panda'",
         "url": "https://www.champssports.com/product/~/316153042104.html",
         "retailer": "champssports", "in_stock": False,
         "available_sizes": [], "price": "$115.00",
         "checked_at": None, "error": None},
        {"sku": "412998710401", "name": "New Balance 550 'White Green'",
         "url": "https://www.footlocker.com/product/~/412998710401.html",
         "retailer": "footlocker", "in_stock": True,
         "available_sizes": ["8.5", "9", "9.5", "10"], "price": "$120.00",
         "checked_at": None, "error": None},
        {"sku": "551829060801", "name": "Yeezy Slide 'Onyx'",
         "url": "https://www.kidsfootlocker.com/product/~/551829060801.html",
         "retailer": "kidsfootlocker", "in_stock": False,
         "available_sizes": [], "price": "$70.00",
         "checked_at": None, "error": "HTTP 403 (Akamai bot challenge)"},
    ],
    "events": [
        {"ts": None, "kind": "restock", "name": "Air Jordan 1 Retro High OG 'Chicago'",
         "sizes": ["9", "10"], "price": "$180.00", "previous_price": None,
         "url": "https://www.footlocker.com/product/~/314206561604.html"},
        {"ts": None, "kind": "restock", "name": "New Balance 550 'White Green'",
         "sizes": ["9.5"], "price": "$120.00", "previous_price": None,
         "url": "https://www.footlocker.com/product/~/412998710401.html"},
        {"ts": None, "kind": "in_stock", "name": "New Balance 550 'White Green'",
         "sizes": ["10"], "price": "$120.00", "previous_price": None,
         "url": "https://www.footlocker.com/product/~/412998710401.html"},
    ],
}


def _payload() -> dict:
    """Proxy a real monitor's state if MONITOR_STATE_URL is set, else sample."""
    state_url = os.environ.get("MONITOR_STATE_URL")
    if state_url:
        try:
            with urllib.request.urlopen(state_url, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                data.setdefault("demo", False)
                return data
        except Exception:  # noqa: BLE001 - fall back to sample on any failure
            pass
    return SAMPLE


# Vercel Python runtime entrypoint: a BaseHTTPRequestHandler subclass `handler`.
from http.server import BaseHTTPRequestHandler  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(_payload()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)
