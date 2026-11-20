"""Availability records shared by every provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone


@dataclass
class SiteOffer:
    """One site that can be booked for a stay starting on a given day."""

    id: str
    name: str
    loop: str
    site_type: str
    max_people: int | None
    price: str | None
    price_max: str | None
    url: str
    spots: int = 1

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "loop": self.loop,
            "type": self.site_type,
            "max_people": self.max_people,
            "price": self.price,
            "price_max": self.price_max,
            "spots": self.spots,
            "url": self.url,
        }


@dataclass
class TypeCount:
    site_type: str
    available: int
    total: int
    price: str | None = None
    price_max: str | None = None

    def to_dict(self) -> dict:
        return {
            "type": self.site_type,
            "available": self.available,
            "total": self.total,
            "price": self.price,
            "price_max": self.price_max,
        }


@dataclass
class DayAvailability:
    date: date
    available: int
    total: int
    by_type: list[TypeCount] = field(default_factory=list)
    sites: list[SiteOffer] = field(default_factory=list)
    walkup: int = 0
    call_center: int = 0

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "available": self.available,
            "total": self.total,
            "walkup": self.walkup,
            "call_center": self.call_center,
            "by_type": [item.to_dict() for item in self.by_type],
            "sites": [site.to_dict() for site in self.sites],
        }


@dataclass
class AvailabilityResult:
    provider: str
    park_id: str
    park_name: str
    park_slug: str
    park_url: str
    start: date
    end: date
    nights: int
    price_note: str
    days: list[DayAvailability]
    fetched_at: datetime
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "park": {
                "id": self.park_id,
                "name": self.park_name,
                "slug": self.park_slug,
                "url": self.park_url,
            },
            "query": {
                "from": self.start.isoformat(),
                "to": self.end.isoformat(),
                "nights": self.nights,
            },
            "price_note": self.price_note,
            "warnings": list(self.warnings),
            "fetched_at": _utc_stamp(self.fetched_at),
            "days": [day.to_dict() for day in self.days],
        }


def _utc_stamp(value: datetime) -> str:
    utc = value.astimezone(timezone.utc).replace(microsecond=0)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
