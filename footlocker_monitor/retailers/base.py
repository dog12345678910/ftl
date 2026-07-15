"""Retailer abstraction so the monitor can watch more than one store.

Foot Locker runs a family of banners (Foot Locker, Kids Foot Locker, Champs
Sports, Footaction) on the *same* commerce platform, so they share the PDP API
shape and only differ by domain. A :class:`Retailer` captures those
per-store differences; adding a store on a different platform is a matter of
subclassing and overriding :meth:`parse`.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from ..parsing import parse_product
from ..product import ProductStatus, WatchedProduct


class Retailer:
    """Describes how to reach and read one store's product API."""

    id: str = "generic"
    name: str = "Generic"
    domains: tuple[str, ...] = ()
    pdp_template: str = ""
    product_url_template: str = ""

    def pdp_url(self, sku: str) -> str:
        return self.pdp_template.format(sku=sku)

    def product_url(self, sku: str) -> str:
        return self.product_url_template.format(sku=sku)

    def matches(self, url: str) -> bool:
        host = urlparse(url).netloc.lower() or url.lower().split("/", 1)[0]
        host = host.split(":", 1)[0]  # strip any port
        # Match on a host boundary so "footlocker.com" doesn't match
        # "kidsfootlocker.com".
        return any(host == d or host.endswith("." + d) for d in self.domains)

    def parse(self, payload: dict[str, Any], watched: WatchedProduct) -> ProductStatus:
        """Parse a PDP payload. Default handles the Foot Locker platform
        shape; override for stores with a different JSON structure."""
        return parse_product(payload, watched, fallback_url=self.product_url(watched.sku))
