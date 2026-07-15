"""Tests for the multi-retailer abstraction."""

from footlocker_monitor.product import WatchedProduct
from footlocker_monitor.retailers import detect_retailer, get_retailer, retailer_ids


def test_registry_has_fl_banners():
    ids = retailer_ids()
    assert {"footlocker", "kidsfootlocker", "champssports", "footaction"} <= set(ids)


def test_detect_retailer_from_url():
    assert detect_retailer("https://www.champssports.com/product/~/123.html") == "champssports"
    assert detect_retailer("https://www.kidsfootlocker.com/product/~/9.html") == "kidsfootlocker"
    assert detect_retailer("https://www.footlocker.com/x") == "footlocker"
    assert detect_retailer("https://example.com/x") is None
    assert detect_retailer("") is None


def test_get_retailer_falls_back_to_footlocker():
    assert get_retailer("nope").id == "footlocker"


def test_retailer_urls():
    champs = get_retailer("champssports")
    assert champs.pdp_url("314206") == "https://www.champssports.com/api/products/pdp/314206"
    assert champs.product_url("314206") == "https://www.champssports.com/product/~/314206.html"


def test_watchedproduct_detects_retailer_from_url():
    w = WatchedProduct.from_config({"url": "https://www.champssports.com/product/~/314206561604.html"})
    assert w.retailer == "champssports"
    assert w.sku == "314206561604"


def test_watchedproduct_explicit_retailer_wins():
    w = WatchedProduct.from_config({"sku": "314206561604", "retailer": "footaction"})
    assert w.retailer == "footaction"


def test_retailer_parse_uses_its_own_product_url():
    champs = get_retailer("champssports")
    payload = {"product": {"name": "Shoe", "stockLevelStatus": "inStock"}}
    status = champs.parse(payload, WatchedProduct(sku="314206561604", retailer="champssports"))
    assert status.url == "https://www.champssports.com/product/~/314206561604.html"
