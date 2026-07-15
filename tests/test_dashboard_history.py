"""Tests for history logging, state snapshot, and the dashboard payload."""

import unittest.mock as m

from footlocker_monitor import history
from footlocker_monitor.config import Config
from footlocker_monitor.dashboard import build_status
from footlocker_monitor.product import ProductStatus, SizeStock, WatchedProduct
from footlocker_monitor.state import RestockEvent, StateStore


def _event(**kw):
    base = dict(sku="1", name="AJ1", url="http://x", newly_available_sizes=["9"],
                price="$180", kind="restock")
    base.update(kw)
    return RestockEvent(**base)


def test_history_round_trip(tmp_path):
    path = str(tmp_path / "hist.jsonl")
    history.append_events(path, [_event(), _event(name="Dunk", kind="in_stock")])
    recent = history.read_recent(path, limit=10)
    assert len(recent) == 2
    # Newest first: the second appended event leads.
    assert recent[0]["name"] == "Dunk"
    assert recent[0]["kind"] == "in_stock"
    assert recent[1]["sizes"] == ["9"]


def test_history_read_missing_file(tmp_path):
    assert history.read_recent(str(tmp_path / "nope.jsonl")) == []


def test_history_append_noops_on_empty(tmp_path):
    path = str(tmp_path / "hist.jsonl")
    history.append_events(path, [])
    assert history.read_recent(path) == []


def test_snapshot_reports_availability_and_error(tmp_path):
    store = StateStore(str(tmp_path / "s.json"))
    w = WatchedProduct(sku="1", retailer="champssports")
    ok = ProductStatus(sku="1", name="AJ1", url="http://x", in_stock=True,
                       sizes=[SizeStock("9", True), SizeStock("10", False)], price="$180")
    store.evaluate(w, ok)
    # An errored product should still appear (with its error), not vanish.
    err = ProductStatus(sku="2", name="Dunk", url="http://y", in_stock=False, error="HTTP 403")
    store.evaluate(WatchedProduct(sku="2"), err)

    snap = {row["sku"]: row for row in store.snapshot()}
    assert snap["1"]["in_stock"] is True
    assert snap["1"]["available_sizes"] == ["9"]
    assert snap["1"]["retailer"] == "champssports"
    assert snap["2"]["error"] == "HTTP 403"


def test_build_status_payload(tmp_path):
    state = str(tmp_path / "s.json")
    hist = str(tmp_path / "h.jsonl")
    store = StateStore(state)
    store.evaluate(WatchedProduct(sku="1"),
                   ProductStatus(sku="1", name="AJ1", url="http://x", in_stock=True,
                                 sizes=[SizeStock("9", True)]))
    store.save()
    history.append_events(hist, [_event()])

    config = Config(watch=[WatchedProduct(sku="1")], state_file=state, history_file=hist)
    status = build_status(config)
    assert status["watched_count"] == 1
    assert status["in_stock_count"] == 1
    assert len(status["events"]) == 1
    assert status["products"][0]["name"] == "AJ1"
