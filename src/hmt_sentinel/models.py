"""Core data models."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class AvailabilityState(str, Enum):
    IN_STOCK = "IN_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    COMING_SOON = "COMING_SOON"
    UNKNOWN = "UNKNOWN"


@dataclass
class Product:
    """A discovered product from one website."""
    domain: str                          # "hmtwatches.store" or "hmtwatches.in"
    product_id: str                      # site-specific stable identifier
    name: str
    url: str
    price: Optional[str] = None
    currency: str = "INR"
    model_ref: Optional[str] = None
    availability: AvailabilityState = AvailabilityState.UNKNOWN
    availability_reason: Optional[str] = None
    first_seen: Optional[datetime] = None
    last_checked: Optional[datetime] = None
    last_successful_check: Optional[datetime] = None
    last_transition: Optional[datetime] = None
    last_notified: Optional[datetime] = None
    # last known reliable state (not UNKNOWN)
    last_reliable_availability: Optional[AvailabilityState] = None
    missing_from_listing: bool = False

    @property
    def key(self) -> str:
        return f"{self.domain}::{self.product_id}"

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "product_id": self.product_id,
            "name": self.name,
            "url": self.url,
            "price": self.price,
            "currency": self.currency,
            "model_ref": self.model_ref,
            "availability": self.availability.value,
            "availability_reason": self.availability_reason,
            "first_seen": _dt_str(self.first_seen),
            "last_checked": _dt_str(self.last_checked),
            "last_successful_check": _dt_str(self.last_successful_check),
            "last_transition": _dt_str(self.last_transition),
            "last_notified": _dt_str(self.last_notified),
            "last_reliable_availability": (
                self.last_reliable_availability.value
                if self.last_reliable_availability else None
            ),
            "missing_from_listing": self.missing_from_listing,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Product":
        return cls(
            domain=d["domain"],
            product_id=d["product_id"],
            name=d["name"],
            url=d["url"],
            price=d.get("price"),
            currency=d.get("currency", "INR"),
            model_ref=d.get("model_ref"),
            availability=AvailabilityState(d.get("availability", "UNKNOWN")),
            availability_reason=d.get("availability_reason"),
            first_seen=_parse_dt(d.get("first_seen")),
            last_checked=_parse_dt(d.get("last_checked")),
            last_successful_check=_parse_dt(d.get("last_successful_check")),
            last_transition=_parse_dt(d.get("last_transition")),
            last_notified=_parse_dt(d.get("last_notified")),
            last_reliable_availability=(
                AvailabilityState(d["last_reliable_availability"])
                if d.get("last_reliable_availability") else None
            ),
            missing_from_listing=d.get("missing_from_listing", False),
        )


@dataclass
class RunSummary:
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: Optional[datetime] = None
    store_discovery_ok: Optional[bool] = None
    in_discovery_ok: Optional[bool] = None
    store_products_found: int = 0
    in_products_found: int = 0
    store_checked: int = 0
    in_checked: int = 0
    in_stock: int = 0
    out_of_stock: int = 0
    coming_soon: int = 0
    unknown: int = 0
    notifications_sent: int = 0
    notifications_failed: int = 0
    errors: list[str] = field(default_factory=list)


def _dt_str(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
