"""Fetches and parses Foot Locker product availability.

Foot Locker exposes a product-detail JSON API used by its own storefront:

    https://www.footlocker.com/api/products/pdp/<sku>

The response shape changes over time and varies by region, so the parser
here is deliberately defensive: it walks the JSON looking for the fields it
needs rather than assuming a fixed structure. That keeps the monitor working
across minor API tweaks. The endpoint is protected by Akamai bot management,
so a valid User-Agent (and sometimes cookies / a proxy) is required — all of
which are configurable.
"""

from __future__ import annotations

import random
import time
from typing import Any, Iterable, Optional

import requests

from .product import ProductStatus, SizeStock, WatchedProduct

DEFAULT_PDP_TEMPLATE = "https://www.footlocker.com/api/products/pdp/{sku}"

# A realistic desktop Chrome UA. Foot Locker blocks obvious bot UAs.
DEFAULT_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

# JSON keys that commonly indicate "this variant is buyable".
_IN_STOCK_TOKENS = {"instock", "in_stock", "available", "true", "purchasable"}
_OUT_OF_STOCK_TOKENS = {"outofstock", "out_of_stock", "unavailable", "soldout", "false"}


class ScrapeError(Exception):
    """Raised when a product could not be fetched or parsed."""


class FootLockerScraper:
    def __init__(
        self,
        *,
        pdp_template: str = DEFAULT_PDP_TEMPLATE,
        user_agents: Optional[list[str]] = None,
        headers: Optional[dict[str, str]] = None,
        cookies: Optional[dict[str, str]] = None,
        proxies: Optional[dict[str, str]] = None,
        timeout: float = 15.0,
        max_retries: int = 3,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.pdp_template = pdp_template
        self.user_agents = user_agents or DEFAULT_USER_AGENTS
        self.extra_headers = headers or {}
        self.cookies = cookies or {}
        self.proxies = proxies or None
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = session or requests.Session()

    def _headers(self, watched: WatchedProduct) -> dict[str, str]:
        referer = watched.url or f"https://www.footlocker.com/product/~/{watched.sku}.html"
        headers = {
            "User-Agent": random.choice(self.user_agents),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "x-api-lang": "en-US",
            "x-fl-request-id": "restock-monitor",
            "Referer": referer,
            "Connection": "keep-alive",
        }
        headers.update(self.extra_headers)
        return headers

    def fetch(self, watched: WatchedProduct) -> ProductStatus:
        """Fetch and parse a single product. Never raises — returns a status
        object whose ``error`` field is set on failure so one bad product
        doesn't stop the whole run."""
        url = self.pdp_template.format(sku=watched.sku)
        try:
            payload = self._get_json(url, watched)
        except Exception as exc:  # noqa: BLE001 - surfaced via status.error
            return ProductStatus(
                sku=watched.sku,
                name=watched.name or watched.sku,
                url=watched.url or url,
                in_stock=False,
                error=str(exc),
            )
        return parse_product(payload, watched)

    def _get_json(self, url: str, watched: WatchedProduct) -> dict[str, Any]:
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(
                    url,
                    headers=self._headers(watched),
                    cookies=self.cookies,
                    proxies=self.proxies,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last_exc = exc
            else:
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except ValueError as exc:
                        raise ScrapeError(
                            "response was not JSON (Foot Locker may be showing a "
                            "bot-challenge page; try supplying cookies/a proxy)"
                        ) from exc
                if resp.status_code in (403, 429):
                    last_exc = ScrapeError(
                        f"blocked by Foot Locker (HTTP {resp.status_code}); "
                        "supply fresh cookies or a residential proxy"
                    )
                else:
                    last_exc = ScrapeError(f"HTTP {resp.status_code}")

            if attempt < self.max_retries:
                time.sleep(min(2 ** attempt, 8) + random.random())

        raise last_exc or ScrapeError("unknown fetch error")


def parse_product(payload: dict[str, Any], watched: WatchedProduct) -> ProductStatus:
    """Turn a PDP JSON payload into a :class:`ProductStatus`.

    The parser searches the payload for a product object and a list of
    "sellable units" (size variants), tolerating several known key names.
    """
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
        url=watched.url or f"https://www.footlocker.com/product/~/{watched.sku}.html",
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
