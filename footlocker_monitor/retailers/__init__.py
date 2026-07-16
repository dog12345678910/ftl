"""Registry of supported retailers and URL-based detection."""

from __future__ import annotations

from typing import Optional

from .base import Retailer
from .footlocker import ChampsSports, Footaction, FootLocker, KidsFootLocker

_RETAILERS: dict[str, Retailer] = {
    r.id: r
    for r in (FootLocker(), KidsFootLocker(), ChampsSports(), Footaction())
}

DEFAULT_RETAILER = "footlocker"


def get_retailer(retailer_id: str) -> Retailer:
    """Look up a retailer by id, falling back to Foot Locker."""
    return _RETAILERS.get(retailer_id, _RETAILERS[DEFAULT_RETAILER])


def detect_retailer(url: str) -> Optional[str]:
    """Infer the retailer id from a product URL's domain, if recognized."""
    if not url:
        return None
    for retailer in _RETAILERS.values():
        if retailer.matches(url):
            return retailer.id
    return None


def retailer_ids() -> list[str]:
    return list(_RETAILERS)


__all__ = [
    "Retailer",
    "get_retailer",
    "detect_retailer",
    "retailer_ids",
    "DEFAULT_RETAILER",
]
