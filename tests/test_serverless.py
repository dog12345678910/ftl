"""Tests for the stateless serverless sweep (Vercel cron path)."""

import json
import unittest.mock as m

from footlocker_monitor.notifiers.base import Notifier
from footlocker_monitor.product import ProductStatus, SizeStock, WatchedProduct
from footlocker_monitor.serverless import UpstashRedis, run_sweep


class _FakeScraper:
    """Returns a scripted ProductStatus per sku."""

    def __init__(self):
        self.by_sku = {}

    def set(self, sku, in_stock, sizes):
        self.by_sku[sku] = ProductStatus(
            sku=sku, name="Test " + sku, url="http://x/" + sku, in_stock=in_stock,
            sizes=[SizeStock(s, v) for s, v in sizes.items()], price="$180",
        )

    def fetch(self, watched):
        return self.by_sku[watched.sku]


class _Capture(Notifier):
    def __init__(self):
        self.events = []

    def notify(self, event):
        self.events.append(event)


def test_run_sweep_detects_restock_across_invocations():
    watch = [WatchedProduct(sku="314206561604", sizes=["10"])]
    scraper = _FakeScraper()
    cap = _Capture()

    # Invocation 1: out of stock. No alert. State captured.
    scraper.set("314206561604", in_stock=False, sizes={"9": False, "10": False})
    r1 = run_sweep(watch, {}, scraper, [cap])
    assert r1.events == []
    assert cap.events == []
    assert r1.status["watched_count"] == 1
    assert r1.status["products"][0]["in_stock"] is False

    # Invocation 2: size 10 restocks. Feed r1.state back in (as Redis would).
    scraper.set("314206561604", in_stock=True, sizes={"9": False, "10": True})
    r2 = run_sweep(watch, r1.state, scraper, [cap])
    assert len(r2.events) == 1
    assert r2.events[0].kind == "restock"
    assert r2.events[0].newly_available_sizes == ["10"]
    assert len(cap.events) == 1
    assert r2.status["in_stock_count"] == 1

    # Invocation 3: still in stock -> no repeat alert.
    r3 = run_sweep(watch, r2.state, scraper, [cap])
    assert r3.events == []
    assert len(cap.events) == 1


def test_run_sweep_marks_pending_and_first_seen_suppressed():
    watch = [WatchedProduct(sku="111111")]
    scraper = _FakeScraper()
    scraper.set("111111", in_stock=True, sizes={"9": True})
    cap = _Capture()
    r = run_sweep(watch, {}, scraper, [cap])
    # First sighting in stock is suppressed by default (first_seen).
    assert r.events == []
    assert r.status["products"][0]["in_stock"] is True


def test_upstash_client_get_set_round_trip():
    store = {}

    def fake_get(url, headers=None, timeout=None):
        key = url.rsplit("/", 1)[-1]
        return m.Mock(status_code=200, raise_for_status=lambda: None,
                      json=lambda: {"result": store.get(key)})

    def fake_post(url, headers=None, data=None, timeout=None):
        key = url.rsplit("/", 1)[-1]
        store[key] = data
        return m.Mock(status_code=200, raise_for_status=lambda: None)

    r = UpstashRedis("https://x.upstash.io", "tok")
    with m.patch("footlocker_monitor.serverless.requests.get", side_effect=fake_get), \
         m.patch("footlocker_monitor.serverless.requests.post", side_effect=fake_post):
        assert r.get_json("footlocker:state") is None
        r.set_json("footlocker:state", {"a": 1})
        assert r.get_json("footlocker:state") == {"a": 1}


def test_upstash_from_env():
    assert UpstashRedis.from_env({}) is None
    r = UpstashRedis.from_env({
        "UPSTASH_REDIS_REST_URL": "https://x.upstash.io",
        "UPSTASH_REDIS_REST_TOKEN": "tok",
    })
    assert r is not None and r.url == "https://x.upstash.io"
