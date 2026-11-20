"""Lookup entry points used by the CLI and by other Python code."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from campfind.errors import CampfindError
from campfind.http import PoliteClient, ResultCache, cache_key
from campfind.models import (
    AvailabilityResult,
    DayAvailability,
    SiteOffer,
    TypeCount,
)
from campfind.recgov import RecreationGov
from campfind.txparks import TexasParks


def search(
    provider: str,
    park: str,
    start: date,
    *,
    nights: int = 1,
    end: date | None = None,
    weeks: int | None = None,
    client: PoliteClient | None = None,
    cache: ResultCache | None = None,
    refresh: bool = False,
) -> AvailabilityResult:
    """Return per-day open counts and the open sites for one park.

    ``end`` is the last arrival date. ``weeks`` is used only when ``end`` is
    omitted, and it counts weeks of arrival dates starting at ``start``.
    """
    if nights < 1 or nights > 14:
        raise CampfindError("nights must be from 1 to 14")
    if end is None:
        if weeks is None:
            weeks = 1
        if weeks < 1 or weeks > 8:
            raise CampfindError("weeks must be from 1 to 8")
        end = start + timedelta(days=weeks * 7 - 1)
    if end < start:
        raise CampfindError("end date is before the start date")
    if (end - start).days + 1 > 56:
        raise CampfindError("Date range is longer than 8 weeks. Split the lookup.")

    client = client or PoliteClient()
    cache = cache if cache is not None else ResultCache()
    key = cache_key(provider, park, start.isoformat(), end.isoformat(), nights)
    if not refresh:
        cached = cache.get(key)
        if cached is not None:
            return result_from_dict(cached)

    if provider == "txparks":
        result = TexasParks(client).search(park, start, end, nights)
    elif provider == "recgov":
        result = RecreationGov(client).search(park, start, end, nights)
    else:
        raise CampfindError(f"Unknown provider '{provider}'. Use txparks or recgov.")
    cache.put(key, result.to_dict())
    return result


def result_from_dict(data: dict) -> AvailabilityResult:
    days = []
    for day in data["days"]:
        days.append(
            DayAvailability(
                date=date.fromisoformat(day["date"]),
                available=day["available"],
                total=day["total"],
                walkup=day.get("walkup", 0),
                call_center=day.get("call_center", 0),
                by_type=[
                    TypeCount(
                        site_type=item["type"],
                        available=item["available"],
                        total=item["total"],
                        price=item.get("price"),
                        price_max=item.get("price_max"),
                    )
                    for item in day.get("by_type", [])
                ],
                sites=[
                    SiteOffer(
                        id=site["id"],
                        name=site["name"],
                        loop=site.get("loop") or "",
                        site_type=site["type"],
                        max_people=site.get("max_people"),
                        price=site.get("price"),
                        price_max=site.get("price_max"),
                        url=site.get("url") or "",
                        spots=site.get("spots", 1),
                    )
                    for site in day.get("sites", [])
                ],
            )
        )
    fetched = datetime.fromisoformat(data["fetched_at"].replace("Z", "+00:00"))
    query = data["query"]
    park = data["park"]
    return AvailabilityResult(
        provider=data["provider"],
        park_id=park["id"],
        park_name=park["name"],
        park_slug=park.get("slug") or "",
        park_url=park.get("url") or "",
        start=date.fromisoformat(query["from"]),
        end=date.fromisoformat(query["to"]),
        nights=query["nights"],
        price_note=data.get("price_note") or "",
        days=days,
        fetched_at=fetched,
        warnings=list(data.get("warnings") or []),
    )
