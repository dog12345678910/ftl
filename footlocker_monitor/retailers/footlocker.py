"""The Foot Locker family of banners, all on the same commerce platform."""

from __future__ import annotations

from .base import Retailer


class _FLBanner(Retailer):
    """Shared config for Foot Locker banners — same API, different domain."""

    domain: str = ""

    def __init__(self) -> None:
        self.pdp_template = f"https://www.{self.domain}/api/products/pdp/{{sku}}"
        self.product_url_template = f"https://www.{self.domain}/product/~/{{sku}}.html"
        self.domains = (self.domain,)


class FootLocker(_FLBanner):
    id = "footlocker"
    name = "Foot Locker"
    domain = "footlocker.com"


class KidsFootLocker(_FLBanner):
    id = "kidsfootlocker"
    name = "Kids Foot Locker"
    domain = "kidsfootlocker.com"


class ChampsSports(_FLBanner):
    id = "champssports"
    name = "Champs Sports"
    domain = "champssports.com"


class Footaction(_FLBanner):
    id = "footaction"
    name = "Footaction"
    domain = "footaction.com"
