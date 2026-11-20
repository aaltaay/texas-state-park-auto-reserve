"""Parse Texas State Parks availability HTML.

The park page (campgroundDetails.do) renders a 14-day grid. Site type and the
nightly rate table sit next to that grid. Later pages of the same grid come
back as an HTML fragment with the same markup.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from bs4 import BeautifulSoup

from campfind.errors import CampfindError
from campfind.money import parse_price

STATUS_LETTERS = {"a", "r", "w", "c", "x"}
SITE_LABEL = re.compile(r"Site:\s*(.*?)\s*\((\d+)\)\s*$")
NEXT_INDEX = re.compile(r"startIdx=(\d+)")
TOTAL_SITES = re.compile(r"out of\s+(\d+)")
SLUG_IN_HREF = re.compile(r"/camping/([^/]+)/r/")


@dataclass
class ParsedSite:
    site_id: str
    name: str
    loop: str = ""
    site_type: str = ""
    max_people: int | None = None
    equipment: str = ""
    nights: dict[date, str] = field(default_factory=dict)


@dataclass
class ParsedPage:
    park_name: str | None
    slug: str | None
    dates: list[date]
    sites: dict[str, ParsedSite]
    next_start: int | None
    reported_total: int | None
    fees: dict[str, tuple[Decimal, Decimal]]


def parse_page(html: str, anchor: date, page_start: int = 0) -> ParsedPage:
    soup = BeautifulSoup(html, "html.parser")
    dates = _dates(soup, anchor)
    sites: dict[str, ParsedSite] = {}
    for link in soup.select("a[aria-label]"):
        label = link.get("aria-label") or ""
        match = SITE_LABEL.search(label)
        if not match:
            continue
        name, site_id = match.group(1).strip(), match.group(2)
        row = link.find_parent("div", class_="br")
        if row is None:
            continue
        site = sites.setdefault(site_id, ParsedSite(site_id=site_id, name=name))
        if link.find_parent(id="calendar") is not None:
            _read_calendar_row(row, site, dates)
        else:
            _read_list_row(row, site)
    if not sites:
        raise CampfindError(
            "The park page did not include a campsite grid. "
            "The date may be outside the booking window."
        )
    return ParsedPage(
        park_name=_park_name(soup),
        slug=_slug(soup),
        dates=dates,
        sites=sites,
        next_start=_next_start(soup, after=page_start),
        reported_total=_reported_total(soup),
        fees=_fees(soup),
    )


def merge_sites(pages: list[ParsedPage]) -> dict[str, ParsedSite]:
    merged: dict[str, ParsedSite] = {}
    for page in pages:
        for site_id, site in page.sites.items():
            current = merged.get(site_id)
            if current is None:
                merged[site_id] = ParsedSite(
                    site_id=site.site_id,
                    name=site.name,
                    loop=site.loop,
                    site_type=site.site_type,
                    max_people=site.max_people,
                    equipment=site.equipment,
                    nights=dict(site.nights),
                )
                continue
            current.nights.update(site.nights)
            if site.loop:
                current.loop = site.loop
            if site.site_type:
                current.site_type = site.site_type
            if site.max_people is not None:
                current.max_people = site.max_people
            if site.equipment:
                current.equipment = site.equipment
            if site.name:
                current.name = site.name
    return merged


def _dates(soup: BeautifulSoup, anchor: date) -> list[date]:
    calendar = soup.select_one("#calendar")
    if calendar is None:
        raise CampfindError("Availability calendar was missing from the park page.")
    header = calendar.find("div", class_="thead")
    if header is None:
        raise CampfindError("Availability calendar has no date header.")
    day_numbers: list[int] = []
    for cell in header.find_all("div", recursive=False):
        classes = cell.get("class") or []
        if "calendar" not in classes:
            continue
        number = cell.find("div", class_="date")
        if number is None:
            continue
        day_numbers.append(int(number.get_text(strip=True)))
    if not day_numbers:
        raise CampfindError("Availability calendar has no days.")
    if day_numbers[0] != anchor.day:
        raise CampfindError(
            f"Calendar starts on day {day_numbers[0]}, expected {anchor.isoformat()}."
        )
    dates: list[date] = []
    cursor = anchor
    for day_number in day_numbers:
        if cursor.day != day_number:
            raise CampfindError(
                f"Calendar day {day_number} did not follow {dates[-1].isoformat()}."
            )
        dates.append(cursor)
        cursor += timedelta(days=1)
    return dates


def _read_calendar_row(row, site: ParsedSite, dates: list[date]) -> None:
    loop = row.find("div", class_="loopName")
    if loop is not None:
        site.loop = loop.get_text(strip=True)
    letters: list[str] = []
    for cell in row.find_all("div", recursive=False):
        classes = cell.get("class") or []
        if "status" not in classes:
            continue
        letter = next((item.lower() for item in classes if item.lower() in STATUS_LETTERS), "")
        letters.append(letter or "?")
    if len(letters) != len(dates):
        raise CampfindError(
            f"Site {site.name} has {len(letters)} days in the grid, expected {len(dates)}."
        )
    for day, letter in zip(dates, letters):
        site.nights[day] = letter


def _read_list_row(row, site: ParsedSite) -> None:
    cells = [
        cell
        for cell in row.find_all("div", recursive=False)
        if "td" in (cell.get("class") or [])
    ]
    people_at = next(
        (index for index, cell in enumerate(cells) if "maxPeopleCell" in (cell.get("class") or [])),
        None,
    )
    if people_at is None or people_at < 2:
        return
    site.loop = site.loop or cells[people_at - 2].get_text(strip=True)
    site.site_type = cells[people_at - 1].get_text(strip=True)
    people = cells[people_at].get_text(strip=True)
    if people.isdigit():
        site.max_people = int(people)
    if people_at + 1 < len(cells):
        equipment = cells[people_at + 1].get_text(" ", strip=True)
        if equipment and "amenitiesicons" not in (cells[people_at + 1].get("class") or []):
            site.equipment = equipment


def _fees(soup: BeautifulSoup) -> dict[str, tuple[Decimal, Decimal]]:
    fees: dict[str, tuple[Decimal, Decimal]] = {}
    for label in soup.select("span[id^=st_type]"):
        suffix = (label.get("id") or "").replace("st_type", "")
        amount = soup.select_one(f"#nt_fees{suffix}")
        if amount is None:
            continue
        parsed = parse_price(amount.get_text(strip=True))
        if parsed is not None:
            fees[label.get_text(strip=True)] = parsed
    return fees


def _next_start(soup: BeautifulSoup, after: int = -1) -> int | None:
    """Smallest site-page index strictly after the page we just read."""
    found: list[int] = []
    for link in soup.find_all("a"):
        link_id = link.get("id") or ""
        if not link_id.startswith("resultNext"):
            continue
        href = link.get("href") or ""
        if "campsitePaging.do" not in href and "startIdx=" not in href:
            continue
        match = NEXT_INDEX.search(href)
        if match:
            found.append(int(match.group(1)))
    later = [index for index in found if index > after]
    if not later:
        return None
    return min(later)


def _reported_total(soup: BeautifulSoup) -> int | None:
    summary = soup.find(class_="matchSummary")
    if summary is None:
        return None
    match = TOTAL_SITES.search(summary.get_text(" ", strip=True))
    if match is None:
        return None
    return int(match.group(1))


def _park_name(soup: BeautifulSoup) -> str | None:
    title = soup.find("title")
    if title is None:
        return None
    text = title.get_text(" ", strip=True)
    match = re.search(r"Campground Details -\s*(.+?),\s*TX", text)
    if match:
        return match.group(1).strip()
    return None


def _slug(soup: BeautifulSoup) -> str | None:
    for link in soup.select("a[href*='/camping/']"):
        match = SLUG_IN_HREF.search(link.get("href") or "")
        if match:
            return match.group(1)
    return None
