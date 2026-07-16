"""Tests for restock change-detection logic."""

import os

from footlocker_monitor.product import ProductStatus, SizeStock, WatchedProduct
from footlocker_monitor.state import StateStore


def _status(sku, sizes, in_stock=None):
    size_objs = [SizeStock(size=s, in_stock=v) for s, v in sizes.items()]
    if in_stock is None:
        in_stock = any(v for v in sizes.values())
    return ProductStatus(sku=sku, name="Test", url="http://x", in_stock=in_stock, sizes=size_objs)


def test_first_seen_flagged(tmp_path):
    store = StateStore(str(tmp_path / "s.json"))
    watched = WatchedProduct(sku="1")
    event = store.evaluate(watched, _status("1", {"9": True}))
    assert event is not None
    assert event.first_seen is True
    assert event.newly_available_sizes == ["9"]


def test_no_alert_when_still_out_of_stock(tmp_path):
    store = StateStore(str(tmp_path / "s.json"))
    watched = WatchedProduct(sku="1")
    store.evaluate(watched, _status("1", {"9": False}))
    event = store.evaluate(watched, _status("1", {"9": False}))
    assert event is None


def test_restock_transition_triggers_alert(tmp_path):
    store = StateStore(str(tmp_path / "s.json"))
    watched = WatchedProduct(sku="1")
    store.evaluate(watched, _status("1", {"9": False, "10": False}))
    event = store.evaluate(watched, _status("1", {"9": True, "10": False}))
    assert event is not None
    assert event.first_seen is False
    assert event.newly_available_sizes == ["9"]


def test_no_repeat_alert_while_in_stock(tmp_path):
    store = StateStore(str(tmp_path / "s.json"))
    watched = WatchedProduct(sku="1")
    store.evaluate(watched, _status("1", {"9": False}))
    first = store.evaluate(watched, _status("1", {"9": True}))
    second = store.evaluate(watched, _status("1", {"9": True}))
    assert first is not None
    assert second is None  # already alerted; no new transition


def test_size_filter_suppresses_unwanted_sizes(tmp_path):
    store = StateStore(str(tmp_path / "s.json"))
    watched = WatchedProduct(sku="1", sizes=["10"])
    store.evaluate(watched, _status("1", {"9": False, "10": False}))
    # Only size 9 restocks — user only wants 10, so no alert.
    event = store.evaluate(watched, _status("1", {"9": True, "10": False}))
    assert event is None
    # Now 10 restocks — alert.
    event = store.evaluate(watched, _status("1", {"9": True, "10": True}))
    assert event is not None
    assert event.newly_available_sizes == ["10"]


def test_error_status_does_not_clobber_state(tmp_path):
    store = StateStore(str(tmp_path / "s.json"))
    watched = WatchedProduct(sku="1")
    store.evaluate(watched, _status("1", {"9": True}))
    err = ProductStatus(sku="1", name="Test", url="http://x", in_stock=False, error="boom")
    assert store.evaluate(watched, err) is None
    # State for sku 1 should be unchanged (still in stock).
    assert store._data["1"]["sizes"] == {"9": True}


def test_state_persists_across_instances(tmp_path):
    path = str(tmp_path / "s.json")
    watched = WatchedProduct(sku="1")
    store = StateStore(path)
    store.evaluate(watched, _status("1", {"9": True}))
    store.save()
    assert os.path.exists(path)

    reloaded = StateStore(path)
    # Already in stock from persisted state -> no new alert.
    assert reloaded.evaluate(watched, _status("1", {"9": True})) is None
