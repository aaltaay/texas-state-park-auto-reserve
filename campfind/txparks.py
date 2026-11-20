"""Texas State Parks availability on texasstateparks.reserveamerica.com."""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from bs4 import BeautifulSoup

from campfind.errors import CampfindError, ParkNotFound
from campfind.http import PoliteClient
from campfind.models import AvailabilityResult, DayAvailability, SiteOffer, TypeCount
from campfind.money import format_price
from campfind.parks import Park, match_parks, resolve_builtin
from campfind.tx_html import ParsedPage, ParsedSite, merge_sites, parse_page

BASE = "https://texasstateparks.reserveamerica.com"
PRICE_NOTE = (
    "Nightly rate is the park's published rate for that site type. "
    "It does not include discounts, entrance fees, or taxes."
)
FACILITY_LINK = re.compile(
    r"/camping/([^/]+)/r/facilityDetails\.do\?contractCode=TX&parkId=(\d+)"
)


class TexasParks:
    """Read the server-rendered availability grid. No login and no booking."""

    def __init__(self, client: PoliteClient):
        self.client = client
        self._session_ready = False

    def search(self, query: str, start: date, end: date, nights: int) -> AvailabilityResult:
        park = self.resolve(query)
        pages: list[ParsedPage] = []
        fees: dict = {}
        reported_total: int | None = None
        slug = park.slug
        name = park.name
        # Cells are single nights. A longer stay is open only when every night
        # is bookable, so the grid has to cover the last night of the last arrival.
        for anchor in _windows(start, _coverage_end(end, nights)):
            for page in self._window(park, anchor):
                pages.append(page)
                fees.update(page.fees)
                if page.reported_total:
                    reported_total = page.reported_total
                if page.slug:
                    slug = page.slug
                if page.park_name:
                    name = page.park_name
        sites = merge_sites(pages)
        warnings = _coverage_warnings(len(sites), reported_total)
        park_url = _details_url(Park(park.provider, park.id, slug, name, park.area, park.aliases))
        return _build_result(
            park_id=park.id,
            park_name=name,
            park_slug=slug,
            park_url=park_url,
            start=start,
            end=end,
            nights=nights,
            sites=sites,
            fees=fees,
            warnings=warnings,
        )

    def resolve(self, query: str) -> Park:
        try:
            return resolve_builtin("txparks", query)
        except ParkNotFound:
            if query.isdigit():
                return Park("txparks", query, "park", f"Texas park {query}")
            return self._from_directory(query)

    def _from_directory(self, query: str) -> Park:
        letter = next((char for char in query if char.isalpha()), "")
        if not letter:
            raise ParkNotFound(f"No Texas park matches '{query}'")
        url = f"{BASE}/campgroundDirectoryList.do?contractCode=TX&letter={letter.upper()}"
        response = self.client.get(url, headers={"Accept": "text/html"})
        found: dict[str, Park] = {}
        soup = BeautifulSoup(response.text, "html.parser")
        for link in soup.select("a[href*='facilityDetails.do']"):
            match = FACILITY_LINK.search(link.get("href") or "")
            if match is None:
                continue
            name = link.get_text(" ", strip=True)
            if not name or name.lower() in {"map", "enter date"}:
                continue
            slug, park_id = match.group(1), match.group(2)
            found[park_id] = Park("txparks", park_id, slug, name)
        if not found:
            raise ParkNotFound(f"No Texas park matches '{query}'")
        try:
            return match_parks(query, list(found.values()))
        except ParkNotFound as exc:
            raise ParkNotFound(
                f"No Texas park on the '{letter.upper()}' directory page matches '{query}'."
            ) from exc

    def _window(self, park: Park, anchor: date) -> list[ParsedPage]:
        url = _details_url(park)
        self._ensure_session(url)
        form = {
            "contractCode": "TX",
            "parkId": park.id,
            "siteTypeFilter": "ALL",
            "availStatus": "",
            "submitSiteForm": "true",
            "search": "site",
            # Ask for one night so each cell is that night, not a pre-baked stay.
            "lengthOfStay": "1",
            "campingDate": anchor.strftime("%m/%d/%Y"),
            "campingDateFlex": "2w",
            "currentMaximumWindow": "5",
        }
        response = self.client.post(
            url,
            data=form,
            headers={"Referer": url, "Accept": "text/html"},
        )
        first = parse_page(response.text, anchor, page_start=0)
        pages = [first]
        start_idx = first.next_start
        seen = {0}
        while start_idx is not None and start_idx not in seen and len(pages) < 12:
            seen.add(start_idx)
            # The park page asks for the next 25 sites here. robots.txt asks
            # crawlers to skip this path, so it is only used to finish the one
            # park in this lookup, and the client waits between requests.
            fragment = self.client.get(
                f"{BASE}/campsitePaging.do?contractCode=TX&parkId={park.id}&startIdx={start_idx}",
                headers={
                    "Referer": url,
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "*/*",
                },
            )
            if "id='calendar'" not in fragment.text and 'id="calendar"' not in fragment.text:
                break
            page = parse_page(fragment.text, anchor, page_start=start_idx)
            pages.append(page)
            start_idx = page.next_start
        return pages

    def _ensure_session(self, url: str) -> None:
        if self._session_ready:
            return
        self.client.get(url, headers={"Accept": "text/html"})
        self._session_ready = True


def _details_url(park: Park) -> str:
    if park.slug and park.slug != "park":
        return (
            f"{BASE}/camping/{park.slug}/r/campgroundDetails.do"
            f"?contractCode=TX&parkId={park.id}"
        )
    return f"{BASE}/campgroundDetails.do?contractCode=TX&parkId={park.id}"


def _coverage_warnings(found: int, reported: int | None) -> list[str]:
    if reported is not None and found < reported:
        return [
            f"Read {found} of {reported} sites. "
            "Open counts can be short if a page was missing."
        ]
    return []


def _coverage_end(end: date, nights: int) -> date:
    return end + timedelta(days=max(nights, 1) - 1)


def _windows(start: date, end: date):
    cursor = start
    while cursor <= end:
        yield cursor
        cursor += timedelta(days=14)


def _build_result(
    *,
    park_id: str,
    park_name: str,
    park_slug: str,
    park_url: str,
    start: date,
    end: date,
    nights: int,
    sites: dict[str, ParsedSite],
    fees: dict,
    warnings: list[str],
) -> AvailabilityResult:
    days: list[DayAvailability] = []
    cursor = start
    while cursor <= end:
        open_counts: Counter[str] = Counter()
        total_counts: Counter[str] = Counter()
        offers: list[SiteOffer] = []
        walkup = 0
        call_center = 0
        stay = [cursor + timedelta(days=offset) for offset in range(nights)]
        for site in sites.values():
            letters = [site.nights.get(day) for day in stay]
            if not letters or letters[0] is None:
                continue
            site_type = site.site_type or "Unknown"
            total_counts[site_type] += 1
            if _letters_open(letters):
                open_counts[site_type] += 1
                low, high = format_price(fees.get(site.site_type))
                offers.append(
                    SiteOffer(
                        id=site.site_id,
                        name=site.name,
                        loop=site.loop,
                        site_type=site_type,
                        max_people=site.max_people,
                        price=low,
                        price_max=high,
                        url=_site_url(park_slug, park_id, site.site_id),
                    )
                )
            elif all(letter == "w" for letter in letters):
                walkup += 1
            elif all(letter == "c" for letter in letters):
                call_center += 1
        offers.sort(key=lambda item: (_sort_name(item.site_type), _sort_name(item.name)))
        by_type = []
        for site_type in sorted(total_counts):
            low, high = format_price(fees.get(site_type))
            by_type.append(
                TypeCount(
                    site_type=site_type,
                    available=open_counts[site_type],
                    total=total_counts[site_type],
                    price=low,
                    price_max=high,
                )
            )
        days.append(
            DayAvailability(
                date=cursor,
                available=sum(open_counts.values()),
                total=sum(total_counts.values()),
                by_type=by_type,
                sites=offers,
                walkup=walkup,
                call_center=call_center,
            )
        )
        cursor += timedelta(days=1)
    return AvailabilityResult(
        provider="txparks",
        park_id=park_id,
        park_name=park_name,
        park_slug=park_slug,
        park_url=park_url,
        start=start,
        end=end,
        nights=nights,
        price_note=PRICE_NOTE,
        days=days,
        fetched_at=datetime.now(timezone.utc),
        warnings=warnings,
    )


def _letters_open(letters: list[str | None]) -> bool:
    return bool(letters) and all(letter == "a" for letter in letters)


def _site_url(slug: str, park_id: str, site_id: str) -> str:
    if slug and slug != "park":
        return (
            f"{BASE}/camping/{slug}/r/campsiteDetails.do"
            f"?contractCode=TX&parkId={park_id}&siteId={site_id}"
        )
    return f"{BASE}/campsiteDetails.do?contractCode=TX&parkId={park_id}&siteId={site_id}"


def _sort_name(value: str) -> str:
    return re.sub(r"\d+", lambda match: match.group(0).zfill(6), value.lower())
