"""End-to-end integration test over a REAL HTTP socket.

Unlike the unit tests (which mock the network), this spins up an actual HTTP
server serving a Foot Locker-shaped PDP payload, points the real Scraper at it,
and drives a full ``Monitor.check_once()`` — exercising requests → fetch →
parse → change-detection → notification over a live socket. It proves the
plumbing works for real; the only thing it can't cover is Foot Locker's own
Akamai edge, which depends on the deploy network.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from footlocker_monitor.config import Config
from footlocker_monitor.monitor import Monitor
from footlocker_monitor.notifiers.base import Notifier
from footlocker_monitor.product import WatchedProduct


# A realistic Foot Locker PDP payload (trimmed to the fields the parser reads).
def _payload(in_stock: bool) -> dict:
    status = "inStock" if in_stock else "outOfStock"
    return {
        "product": {
            "name": "Jordan Retro 1 High OG",
            "price": {"formattedValue": "$180.00"},
            "sellableUnits": [
                {"code": "u9", "stockLevelStatus": "outOfStock",
                 "attributes": [{"type": "size", "value": "9"}]},
                {"code": "u10", "stockLevelStatus": status,
                 "attributes": [{"type": "size", "value": "10"}]},
            ],
        }
    }


class _CaptureNotifier(Notifier):
    """A notifier that records events so the test can assert on them."""

    events: list = []

    def notify(self, event) -> None:
        _CaptureNotifier.events.append(event)


@pytest.fixture
def fake_footlocker():
    """Serve a PDP payload whose stock we can flip at runtime."""
    state = {"in_stock": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            return

        def do_GET(self):
            body = json.dumps(_payload(state["in_stock"])).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, port
    finally:
        server.shutdown()


def test_full_pipeline_detects_restock_over_http(tmp_path, fake_footlocker):
    state, port = fake_footlocker
    _CaptureNotifier.events = []

    config = Config(
        watch=[WatchedProduct(sku="314206561604", name="AJ1", sizes=["10"])],
        notifiers=[{"type": "console"}],
        per_product_delay=0,
        state_file=str(tmp_path / "state.json"),
        history_file=str(tmp_path / "hist.jsonl"),
        # Point the real scraper at our local server (a real HTTP endpoint).
        pdp_template=f"http://127.0.0.1:{port}/api/products/pdp/{{sku}}",
    )
    monitor = Monitor(config)
    monitor.notifiers.append(_CaptureNotifier())

    # Sweep 1: size 10 is out of stock -> no alert.
    assert monitor.check_once() == []
    assert _CaptureNotifier.events == []

    # Restock happens: size 10 comes into stock.
    state["in_stock"] = True

    # Sweep 2: real HTTP fetch sees the change -> exactly one restock alert.
    events = monitor.check_once()
    assert len(events) == 1
    assert events[0].kind == "restock"
    assert events[0].newly_available_sizes == ["10"]
    assert events[0].price == "$180.00"
    assert len(_CaptureNotifier.events) == 1

    # Sweep 3: still in stock -> no repeat alert.
    assert monitor.check_once() == []

    # History file recorded the restock.
    from footlocker_monitor import history
    recent = history.read_recent(config.history_file)
    assert len(recent) == 1 and recent[0]["name"] == "Jordan Retro 1 High OG"
