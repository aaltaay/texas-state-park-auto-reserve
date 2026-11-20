"""Recreation.gov campground availability.

Uses the public month grid at
/api/camps/availability/campground/{id}/month
and campground metadata from /api/camps/campgrounds/{id}.
RIDB is not required.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from campfind.errors import AmbiguousPark, CampfindError, ParkNotFound
from campfind.http import PoliteClient
from campfind.models import AvailabilityResult, DayAvailability, SiteOffer, TypeCount
from campfind.money import format_price, parse_price
from campfind.parks import Park, resolve_builtin

API = "https://www.recreation.gov/api"
OPEN_STATUS = {"available", "open"}
PRICE_NOTE = (
    "Price is the Recreation.gov per-night rate for that site type "
    "when a published season covers the date."
)


class RecreationGov:
    def __init__(self, client: PoliteClient):
        self.client = client

    def search(self, query: str, start: date, end: date, nights: int) -> AvailabilityResult:
        park = self.resolve(query)
        last_night = end + timedelta(days=nights - 1)
        raw_sites: dict[str, dict] = {}
        for month in _months(start, last_night):
            payload = self.client.get_json(
                f"{API}/camps/availability/campground/{park.id}/month",
                params={"start_date": f"{month.isoformat()}T00:00:00.000Z"},
            )
            _absorb(raw_sites, payload.get("campsites") or {})
        if not raw_sites:
            raise CampfindError(f"No campsites returned for {park.name} ({park.id}).")
        name = park.name
        try:
            meta = self.client.get_json(f"{API}/camps/campgrounds/{park.id}")
            facility = meta.get("campground") or {}
            name = facility.get("facility_name") or name
        except CampfindError:
            pass
        rates = self._rates(park.id)
        return _build_result(park, name, start, end, nights, raw_sites, rates)

    def resolve(self, query: str) -> Park:
        if query.isdigit():
            return Park("recgov", query, query, f"Campground {query}")
        try:
            return resolve_builtin("recgov", query)
        except ParkNotFound:
            return self._search_name(query)

    def _search_name(self, query: str) -> Park:
        payload = self.client.get_json(
            f"{API}/search",
            params={"q": query, "size": 10, "fq": "entity_type:campground"},
        )
        matches: list[Park] = []
        for item in payload.get("results") or []:
            if not isinstance(item, dict):
                continue
            if not _keep_result(item, query):
                continue
            entity_id = str(item.get("entity_id") or "")
            name = str(item.get("name") or entity_id)
            if not entity_id:
                continue
            area = str(item.get("parent_name") or "")
            matches.append(
                Park("recgov", entity_id, _slug(name), _title(name), area)
            )
        if not matches:
            raise ParkNotFound(f"No Recreation.gov campground matches '{query}'.")
        if len(matches) > 1:
            raise AmbiguousPark(
                query,
                [f"{park.name} ({park.id}, {park.area})".strip() for park in matches],
            )
        return matches[0]

    def _rates(self, facility_id: str) -> list[dict]:
        try:
            payload = self.client.get_json(f"{API}/camps/campgrounds/{facility_id}/rates")
        except CampfindError:
            return []
        return list(payload.get("rates_list") or [])


def _absorb(store: dict[str, dict], campsites: dict) -> None:
    for site_id, raw in campsites.items():
        if not isinstance(raw, dict):
            continue
        current = store.get(str(site_id))
        if current is None:
            store[str(site_id)] = raw
            continue
        availabilities = current.setdefault("availabilities", {})
        availabilities.update(raw.get("availabilities") or {})
        incoming = raw.get("quantities")
        if isinstance(incoming, dict):
            quantities = current.setdefault("quantities", {})
            quantities.update(incoming)


def _build_result(
    park: Park,
    name: str,
    start: date,
    end: date,
    nights: int,
    raw_sites: dict[str, dict],
    rates: list[dict],
) -> AvailabilityResult:
    visible = {
        site_id: raw
        for site_id, raw in raw_sites.items()
        if not raw.get("hide_external")
    }
    days: list[DayAvailability] = []
    cursor = start
    while cursor <= end:
        stay = [cursor + timedelta(days=offset) for offset in range(nights)]
        open_counts: dict[str, int] = {}
        total_counts: dict[str, int] = {}
        offers: list[SiteOffer] = []
        for site_id, raw in visible.items():
            site_type = str(raw.get("campsite_type") or "Unknown")
            total_counts[site_type] = total_counts.get(site_type, 0) + 1
            if not _stay_open(raw, stay):
                continue
            spots = _spots(raw, stay)
            if spots < 1:
                continue
            low, high = _price(rates, site_type, cursor)
            open_counts[site_type] = open_counts.get(site_type, 0) + spots
            offers.append(
                SiteOffer(
                    id=str(raw.get("campsite_id") or site_id),
                    name=str(raw.get("site") or site_id).strip(),
                    loop=str(raw.get("loop") or "").strip(),
                    site_type=site_type,
                    max_people=raw.get("max_num_people"),
                    price=low,
                    price_max=high,
                    url=f"https://www.recreation.gov/camping/campsites/{raw.get('campsite_id') or site_id}",
                    spots=spots,
                )
            )
        offers.sort(key=lambda item: (item.site_type.lower(), _sort_name(item.name)))
        by_type = [
            TypeCount(
                site_type=site_type,
                available=open_counts.get(site_type, 0),
                total=total,
                price=_price(rates, site_type, cursor)[0],
                price_max=_price(rates, site_type, cursor)[1],
            )
            for site_type, total in sorted(total_counts.items())
        ]
        days.append(
            DayAvailability(
                date=cursor,
                available=sum(open_counts.values()),
                total=sum(total_counts.values()),
                by_type=by_type,
                sites=offers,
            )
        )
        cursor += timedelta(days=1)
    return AvailabilityResult(
        provider="recgov",
        park_id=park.id,
        park_name=_title(name),
        park_slug=park.slug,
        park_url=f"https://www.recreation.gov/camping/campgrounds/{park.id}",
        start=start,
        end=end,
        nights=nights,
        price_note=PRICE_NOTE,
        days=days,
        fetched_at=datetime.now(timezone.utc),
    )


def _stay_open(raw: dict, stay: list[date]) -> bool:
    for day in stay:
        status = _status(raw, day)
        if status is None or status.lower() not in OPEN_STATUS:
            return False
    return True


def _status(raw: dict, day: date) -> str | None:
    availabilities = raw.get("availabilities") or {}
    value = availabilities.get(f"{day.isoformat()}T00:00:00Z")
    if value is None:
        return None
    return str(value)


def _spots(raw: dict, stay: list[date]) -> int:
    reserve_type = str(raw.get("campsite_reserve_type") or "").lower()
    # "Non Site-Specific" contains the words "site-specific", so check the prefix.
    if "site-specific" in reserve_type and not reserve_type.startswith("non"):
        return 1
    quantities = raw.get("quantities") or {}
    amounts: list[int] = []
    for day in stay:
        quantity = quantities.get(f"{day.isoformat()}T00:00:00Z")
        if isinstance(quantity, int):
            amounts.append(quantity)
        else:
            amounts.append(1)
    if not amounts:
        return 1
    return min(amounts)


def _price(rates: list[dict], site_type: str, day: date) -> tuple[str | None, str | None]:
    best_start: date | None = None
    best_amount: str | None = None
    for season in rates:
        season_start = _day(season.get("season_start"))
        season_end = _day(season.get("season_end"))
        if season_start is None or season_end is None:
            continue
        if not (season_start <= day <= season_end):
            continue
        for rate in (season.get("rate_map") or {}).values():
            if not isinstance(rate, dict):
                continue
            if str(rate.get("site_type") or "") != site_type:
                continue
            amount = rate.get("per_night")
            if amount in (None, "", 0):
                continue
            parsed = parse_price(str(amount))
            if parsed is None:
                continue
            if best_start is None or season_start >= best_start:
                best_start = season_start
                best_amount = format_price(parsed)[0]
    if best_amount is None:
        return None, None
    return best_amount, best_amount


def _months(start: date, end: date):
    cursor = date(start.year, start.month, 1)
    last = date(end.year, end.month, 1)
    while cursor <= last:
        yield cursor
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)


def _day(value: object) -> date | None:
    if not value:
        return None
    text = str(value)
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _keep_result(item: dict, query: str) -> bool:
    state = ""
    for address in item.get("addresses") or []:
        if isinstance(address, dict) and address.get("state_code"):
            state = str(address["state_code"]).upper()
            break
    if state and state not in {"TX", "TEXAS"}:
        return _slug(str(item.get("name") or "")) == _slug(query)
    return True


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _title(value: str) -> str:
    return " ".join(part.capitalize() if part.isupper() else part for part in value.split())


def _sort_name(value: str) -> str:
    return re.sub(r"\d+", lambda match: match.group(0).zfill(6), value.lower())
