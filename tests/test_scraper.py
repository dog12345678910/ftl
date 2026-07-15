"""Parser tests against realistic PDP payload shapes (no network)."""

from footlocker_monitor.product import WatchedProduct, extract_sku
from footlocker_monitor.scraper import parse_product, _coerce_stock


def test_extract_sku_from_url():
    url = "https://www.footlocker.com/product/~/314206561604.html"
    assert extract_sku(url) == "314206561604"


def test_extract_sku_fallback_to_digit_run():
    assert extract_sku("some-slug-98765432.html") == "98765432"
    assert extract_sku("no-digits-here") is None


def test_coerce_stock_tokens():
    assert _coerce_stock("inStock") is True
    assert _coerce_stock("outOfStock") is False
    assert _coerce_stock(True) is True
    assert _coerce_stock(5) is True
    assert _coerce_stock(0) is False
    assert _coerce_stock(None) is False
    assert _coerce_stock("SOLD_OUT") is False


def test_parse_product_sellable_units_with_attributes():
    payload = {
        "product": {
            "name": "Air Jordan 1",
            "price": {"formattedValue": "$180.00"},
            "sellableUnits": [
                {
                    "code": "SKU-9",
                    "stockLevelStatus": "inStock",
                    "attributes": [{"type": "size", "value": "9"}],
                },
                {
                    "code": "SKU-10",
                    "stockLevelStatus": "outOfStock",
                    "attributes": [{"type": "size", "value": "10"}],
                },
            ],
        }
    }
    watched = WatchedProduct(sku="314206561604")
    status = parse_product(payload, watched)

    assert status.name == "Air Jordan 1"
    assert status.price == "$180.00"
    assert status.in_stock is True
    assert status.available_sizes == ["9"]
    assert status.size_state() == {"9": True, "10": False}


def test_parse_product_flat_sizes_shape():
    payload = {
        "productData": {
            "productName": "Nike Dunk",
            "variantOptions": [
                {"size": "8", "inStock": True},
                {"size": "8.5", "inStock": False},
            ],
        }
    }
    status = parse_product(payload, WatchedProduct(sku="111"))
    assert status.name == "Nike Dunk"
    assert status.available_sizes == ["8"]


def test_parse_product_no_sizes_uses_product_flag():
    payload = {"product": {"name": "Some Shoe", "stockLevelStatus": "outOfStock"}}
    status = parse_product(payload, WatchedProduct(sku="222"))
    assert status.sizes == []
    assert status.in_stock is False


def test_wants_size_filtering():
    w = WatchedProduct(sku="1", sizes=["9.5", "10"])
    assert w.wants_size("9.5") is True
    assert w.wants_size("10.0") is True   # normalized
    assert w.wants_size("11") is False
    assert WatchedProduct(sku="1").wants_size("anything") is True
