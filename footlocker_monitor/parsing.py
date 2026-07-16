"""Defensive parsing of PDP JSON payloads into :class:`ProductStatus`.

Foot Locker (and its sibling banners, which run the same commerce platform)
expose a product-detail JSON API. The response shape changes over time and
varies by region, so the parser here walks the JSON looking for the fields it
needs rather than assuming a fixed structure. That keeps the monitor working
across minor API tweaks.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from .product import ProductStatus, SizeStock, WatchedProduct

# JSON keys/tokens that commonly indicate "this variant is buyable".
_IN_STOCK_TOKENS = {"instock", "in_stock", "available", "true", "purchasable"}
_OUT_OF_STOCK_TOKENS = {"outofstock", "out_of_stock", "unavailable", "soldout", "false"}


def parse_product(
    payload: dict[str, Any],
    watched: WatchedProduct,
    fallback_url: Optional[str] = None,
) -> ProductStatus:
    """Turn a PDP JSON payload into a :class:`ProductStatus`.

    ``fallback_url`` is used as the product link when the watch entry didn't
    supply one (each retailer passes its own product-page URL).
    """
    if fallback_url is None:
        fallback_url = f"https://www.footlocker.com/product/~/{watched.sku}.html"

    product = _find_product(payload)
    name = _first_str(product, ("name", "productName", "title")) or watched.name or watched.sku
    price = _find_price(product)
    image = _find_image(product)

    sizes = list(_parse_sizes(product))
    if not sizes:
        # No per-size info — fall back to a product-level availability flag.
        overall = _coerce_stock(
            _first(product, ("stockLevelStatus", "availability", "inStock", "status"))
        )
        in_stock = bool(overall)
    else:
        in_stock = any(s.in_stock for s in sizes)

    return ProductStatus(
        sku=watched.sku,
        name=str(name),
        url=watched.url or fallback_url,
        in_stock=in_stock,
        sizes=sizes,
        price=price,
        image=image,
    )


def _parse_sizes(product: dict[str, Any]) -> Iterable[SizeStock]:
    units = _find_list(product, ("sellableUnits", "variantOptions", "sizes", "skus", "variants"))
    for unit in units:
        if not isinstance(unit, dict):
            continue
        size = _extract_size(unit)
        if size is None:
            continue
        raw_status = _first(
            unit,
            ("stockLevelStatus", "stockLevel", "availability", "inStock", "status", "purchasable"),
        )
        in_stock = _coerce_stock(raw_status)
        sku = _first_str(unit, ("code", "sku", "id"))
        yield SizeStock(size=str(size), in_stock=in_stock, sku=sku)


def _extract_size(unit: dict[str, Any]) -> Optional[str]:
    direct = _first_str(unit, ("size", "displaySize", "sizeValue", "value"))
    if direct:
        return direct
    # Foot Locker nests size under attributes: [{type: "size", value: "10.5"}]
    for attrs_key in ("attributes", "variantOptionQualifiers"):
        attrs = unit.get(attrs_key)
        if isinstance(attrs, list):
            for attr in attrs:
                if not isinstance(attr, dict):
                    continue
                label = str(attr.get("type") or attr.get("name") or attr.get("qualifier") or "").lower()
                if "size" in label:
                    val = attr.get("value") or attr.get("displayValue")
                    if val is not None:
                        return str(val)
    return None


def _coerce_stock(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if value is None:
        return False
    token = str(value).strip().lower().replace(" ", "").replace("-", "")
    if token in _IN_STOCK_TOKENS:
        return True
    if token in _OUT_OF_STOCK_TOKENS:
        return False
    # Heuristic fallbacks for unseen tokens.
    if "out" in token or "sold" in token or "unavail" in token:
        return False
    if "in" in token or "avail" in token:
        return True
    return False


# --- generic JSON walking helpers -----------------------------------------


def _find_product(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    for key in ("product", "productData", "data", "pdp"):
        val = payload.get(key)
        if isinstance(val, dict):
            return val
    return payload


def _find_list(product: dict[str, Any], keys: tuple[str, ...]) -> list[Any]:
    for key in keys:
        val = product.get(key)
        if isinstance(val, list) and val:
            return val
    return []


def _first(obj: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in obj and obj[key] is not None:
            return obj[key]
    return None


def _first_str(obj: dict[str, Any], keys: tuple[str, ...]) -> Optional[str]:
    val = _first(obj, keys)
    if val is None:
        return None
    if isinstance(val, (str, int, float)):
        text = str(val).strip()
        return text or None
    return None


def _find_price(product: dict[str, Any]) -> Optional[str]:
    price = _first(product, ("price", "sellingPrice", "originalPrice"))
    if isinstance(price, dict):
        formatted = _first_str(price, ("formattedValue", "value", "amount"))
        if formatted:
            return formatted if str(formatted).startswith("$") else f"${formatted}"
    elif isinstance(price, (str, int, float)):
        return str(price)
    return None


def _find_image(product: dict[str, Any]) -> Optional[str]:
    img = _first(product, ("image", "imageUrl", "images"))
    if isinstance(img, list) and img:
        first = img[0]
        if isinstance(first, dict):
            return _first_str(first, ("url", "src", "href"))
        return str(first)
    if isinstance(img, dict):
        return _first_str(img, ("url", "src", "href"))
    if isinstance(img, str):
        return img
    return None
