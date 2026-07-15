"""Fetches product availability from Foot Locker (and sibling banners).

The heavy lifting of turning a PDP JSON payload into a :class:`ProductStatus`
lives in :mod:`footlocker_monitor.parsing`; per-store URLs and any parsing
quirks live in :mod:`footlocker_monitor.retailers`. This module is just the
HTTP layer: it picks the right retailer for each watched product, fetches the
PDP endpoint with realistic headers/retries, and hands the payload to the
retailer to parse.

The endpoints are protected by Akamai bot management, so a valid User-Agent
(and sometimes cookies / a proxy) is required — all configurable.
"""

from __future__ import annotations

import random
import time
from typing import Any, Optional

import requests

# Re-exported for backwards compatibility with earlier imports/tests.
from .parsing import parse_product, _coerce_stock  # noqa: F401
from .product import ProductStatus, WatchedProduct
from .retailers import Retailer, get_retailer

# A realistic desktop Chrome UA. Foot Locker blocks obvious bot UAs.
DEFAULT_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]


class ScrapeError(Exception):
    """Raised when a product could not be fetched or parsed."""


class Scraper:
    """Retailer-aware fetcher. One instance handles every watched store."""

    def __init__(
        self,
        *,
        pdp_template: str = "",
        user_agents: Optional[list[str]] = None,
        headers: Optional[dict[str, str]] = None,
        cookies: Optional[dict[str, str]] = None,
        proxies: Optional[dict[str, str]] = None,
        timeout: float = 15.0,
        max_retries: int = 3,
        session: Optional[requests.Session] = None,
    ) -> None:
        # An explicit pdp_template overrides every retailer's default endpoint
        # (handy for pointing at a regional API or a debugging proxy).
        self.pdp_template = pdp_template or ""
        self.user_agents = user_agents or DEFAULT_USER_AGENTS
        self.extra_headers = headers or {}
        self.cookies = cookies or {}
        self.proxies = proxies or None
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = session or requests.Session()

    def _headers(self, watched: WatchedProduct, retailer: Retailer) -> dict[str, str]:
        referer = watched.url or retailer.product_url(watched.sku)
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
        retailer = get_retailer(watched.retailer)
        url = self.pdp_template.format(sku=watched.sku) if self.pdp_template else retailer.pdp_url(watched.sku)
        try:
            payload = self._get_json(url, watched, retailer)
        except Exception as exc:  # noqa: BLE001 - surfaced via status.error
            return ProductStatus(
                sku=watched.sku,
                name=watched.name or watched.sku,
                url=watched.url or retailer.product_url(watched.sku),
                in_stock=False,
                error=str(exc),
            )
        return retailer.parse(payload, watched)

    def _get_json(self, url: str, watched: WatchedProduct, retailer: Retailer) -> dict[str, Any]:
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(
                    url,
                    headers=self._headers(watched, retailer),
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
                            f"response was not JSON ({retailer.name} may be showing a "
                            "bot-challenge page; try supplying cookies/a proxy)"
                        ) from exc
                if resp.status_code in (403, 429):
                    last_exc = ScrapeError(
                        f"blocked by {retailer.name} (HTTP {resp.status_code}); "
                        "supply fresh cookies or a residential proxy"
                    )
                else:
                    last_exc = ScrapeError(f"HTTP {resp.status_code}")

            if attempt < self.max_retries:
                time.sleep(min(2 ** attempt, 8) + random.random())

        raise last_exc or ScrapeError("unknown fetch error")


# Backwards-compatible alias for the original class name.
FootLockerScraper = Scraper
