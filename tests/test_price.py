"""Tests for price parsing and price-drop detection."""

from footlocker_monitor.product import ProductStatus, SizeStock, WatchedProduct, parse_price
from footlocker_monitor.state import StateStore


def test_parse_price_formats():
    assert parse_price("$180.00") == 180.0
    assert parse_price("1,299.99") == 1299.99
    assert parse_price(150) == 150.0
    assert parse_price("free") is None
    assert parse_price(None) is None


def _status(sku, price, in_stock=True):
    return ProductStatus(
        sku=sku, name="Test", url="http://x", in_stock=in_stock,
        sizes=[SizeStock(size="9", in_stock=in_stock)], price=price,
    )


def test_no_price_alert_when_disabled(tmp_path):
    store = StateStore(str(tmp_path / "s.json"), track_price_drops=False)
    w = WatchedProduct(sku="1")
    store.evaluate(w, _status("1", "$200"))
    event = store.evaluate(w, _status("1", "$150"))
    assert event is None  # tracking off


def test_price_drop_triggers_alert(tmp_path):
    store = StateStore(str(tmp_path / "s.json"), track_price_drops=True)
    w = WatchedProduct(sku="1")
    store.evaluate(w, _status("1", "$200"))          # baseline
    event = store.evaluate(w, _status("1", "$150"))  # dropped
    assert event is not None
    assert event.kind == "price_drop"
    assert event.previous_price == "$200"
    assert event.price == "$150"


def test_price_increase_does_not_alert(tmp_path):
    store = StateStore(str(tmp_path / "s.json"), track_price_drops=True)
    w = WatchedProduct(sku="1")
    store.evaluate(w, _status("1", "$150"))
    event = store.evaluate(w, _status("1", "$200"))
    assert event is None


def test_target_price_crossing(tmp_path):
    store = StateStore(str(tmp_path / "s.json"), track_price_drops=True)
    w = WatchedProduct(sku="1", target_price=160.0)
    # Use out-of-stock statuses so restock logic doesn't fire — isolate price.
    # First sighting above target: no alert (no baseline, above target).
    assert store.evaluate(w, _status("1", "$200", in_stock=False)) is None
    # Falls to target: alert.
    event = store.evaluate(w, _status("1", "$160", in_stock=False))
    assert event is not None and event.kind == "price_drop"
    # Stays at/under target: no repeat alert.
    assert store.evaluate(w, _status("1", "$160", in_stock=False)) is None


def test_restock_takes_precedence_over_price_drop(tmp_path):
    store = StateStore(str(tmp_path / "s.json"), track_price_drops=True)
    w = WatchedProduct(sku="1")
    store.evaluate(w, _status("1", "$200", in_stock=False))
    event = store.evaluate(w, _status("1", "$150", in_stock=True))
    assert event is not None
    assert event.kind == "restock"
