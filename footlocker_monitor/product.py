"""Data models for watched products and their stock state."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# Foot Locker SKUs look like "314206561604" (12 digits) and appear at the end
# of a product URL, e.g. https://www.footlocker.com/product/~/314206561604.html
_SKU_RE = re.compile(r"(\d{6,})\.html")


@dataclass(frozen=True)
class SizeStock:
    """Availability of a single size variant."""

    size: str
    in_stock: bool
    sku: Optional[str] = None

    def key(self) -> str:
        return f"{self.sku or ''}:{self.size}"


@dataclass
class ProductStatus:
    """A snapshot of a product's availability at a point in time."""

    sku: str
    name: str
    url: str
    in_stock: bool
    sizes: list[SizeStock] = field(default_factory=list)
    price: Optional[str] = None
    image: Optional[str] = None
    error: Optional[str] = None

    @property
    def available_sizes(self) -> list[str]:
        return [s.size for s in self.sizes if s.in_stock]

    def size_state(self) -> dict[str, bool]:
        """Map of size -> in_stock, used for change detection."""
        return {s.size: s.in_stock for s in self.sizes}


@dataclass
class WatchedProduct:
    """A product the user wants to monitor.

    ``sku`` is required for the API lookup. ``sizes`` optionally restricts
    alerts to specific size(s); if empty, any restock triggers an alert.
    ``target_price`` optionally alerts when the price drops to/below a value.
    """

    sku: str
    url: str = ""
    name: str = ""
    sizes: list[str] = field(default_factory=list)
    target_price: Optional[float] = None
    retailer: str = "footlocker"

    @classmethod
    def from_config(cls, entry: dict | str) -> "WatchedProduct":
        if isinstance(entry, str):
            return cls.from_url_or_sku(entry)

        sku = str(entry.get("sku") or "").strip()
        url = str(entry.get("url") or "").strip()
        if not sku and url:
            sku = extract_sku(url) or ""
        if not sku:
            raise ValueError(f"watch entry missing a resolvable sku: {entry!r}")

        sizes = [str(s).strip() for s in entry.get("sizes", []) if str(s).strip()]
        target = entry.get("target_price")
        retailer = str(entry.get("retailer") or "").strip() or _detect_retailer(url)
        return cls(
            sku=sku,
            url=url,
            name=str(entry.get("name") or "").strip(),
            sizes=sizes,
            target_price=parse_price(target) if target is not None else None,
            retailer=retailer,
        )

    @classmethod
    def from_url_or_sku(cls, value: str) -> "WatchedProduct":
        value = value.strip()
        sku = extract_sku(value) or (value if value.isdigit() else "")
        if not sku:
            raise ValueError(f"could not extract a sku from: {value!r}")
        url = value if value.startswith("http") else ""
        return cls(sku=sku, url=url, retailer=_detect_retailer(url))

    def wants_size(self, size: str) -> bool:
        if not self.sizes:
            return True
        return _normalize_size(size) in {_normalize_size(s) for s in self.sizes}

    def to_dict(self) -> dict:
        """Serialize back to a config-style entry (for saving from the UI)."""
        entry: dict = {"sku": self.sku}
        if self.name:
            entry["name"] = self.name
        if self.url:
            entry["url"] = self.url
        entry["sizes"] = list(self.sizes)
        if self.target_price is not None:
            entry["target_price"] = self.target_price
        if self.retailer and self.retailer != "footlocker":
            entry["retailer"] = self.retailer
        return entry


def _detect_retailer(url: str) -> str:
    """Infer retailer id from a URL, defaulting to Foot Locker.

    Imported lazily to avoid a circular import (``retailers`` depends on the
    parser, which depends on this module).
    """
    from .retailers import DEFAULT_RETAILER, detect_retailer

    return detect_retailer(url) or DEFAULT_RETAILER


def parse_price(value: object) -> Optional[float]:
    """Parse a price like ``"$180.00"``, ``"180"`` or ``180.0`` into a float.

    Returns ``None`` when no number can be found (so callers can skip
    price comparisons rather than crash on odd formatting).
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d[\d,]*(?:\.\d+)?", str(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def extract_sku(url: str) -> Optional[str]:
    """Pull the numeric SKU out of a Foot Locker product URL."""
    match = _SKU_RE.search(url)
    if match:
        return match.group(1)
    # Fall back to the longest digit run in the string.
    runs = re.findall(r"\d{6,}", url)
    return max(runs, key=len) if runs else None


def _normalize_size(size: str) -> str:
    """Canonicalize a size string so "10", "10.0" and " 10 " compare equal.

    Only strips trailing zeros that sit *after* a decimal point, so whole
    sizes like "10" are never truncated to "1".
    """
    text = size.strip().lower().replace(" ", "")
    try:
        num = float(text)
    except ValueError:
        return text  # non-numeric sizes (e.g. "M", "XL") compared verbatim
    # Render without a trailing ".0" but keep half sizes like "9.5".
    return f"{num:g}"
