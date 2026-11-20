"""Texas grid parser tests, using saved HTML from the park page shape."""

from datetime import date
from pathlib import Path

from campfind.tx_html import merge_sites, parse_page
from campfind.txparks import _build_result, _coverage_end, _coverage_warnings

FIXTURES = Path(__file__).parent / "fixtures"
ANCHOR = date(2026, 12, 28)


def _page(name: str, page_start: int = 0):
    html = (FIXTURES / name).read_text(encoding="utf-8")
    return parse_page(html, ANCHOR, page_start=page_start)


def test_page_parses_dates_prices_and_next_link():
    page = _page("txparks_page.html")
    assert page.park_name == "Sample State Park"
    assert page.slug == "sample-state-park"
    assert page.dates[0] == date(2026, 12, 28)
    assert page.dates[4] == date(2027, 1, 1)
    assert page.dates[-1] == date(2027, 1, 2)
    assert page.next_start == 25
    assert page.reported_total == 3
    assert page.fees["Campsite Electric"][0] == page.fees["Campsite Electric"][1]
    assert str(page.fees["Group Hall"][0]) == "200.00"
    assert str(page.fees["Group Hall"][1]) == "225.00"

    electric = page.sites["3691"]
    assert electric.name == "050"
    assert electric.loop == "BIG CEDAR"
    assert electric.site_type == "Campsite Electric"
    assert electric.max_people == 8
    assert electric.equipment == "55 Back-In"
    assert electric.nights[date(2026, 12, 28)] == "r"
    assert electric.nights[date(2026, 12, 29)] == "a"
    assert electric.nights[date(2027, 1, 1)] == "a"

    cabin = page.sites["5001"]
    assert cabin.site_type == "Cabin"
    assert cabin.nights[date(2027, 1, 1)] == "w"
    assert cabin.nights[date(2027, 1, 2)] == "c"


def test_second_page_merges_without_going_backwards():
    first = _page("txparks_page.html", page_start=0)
    second = _page("txparks_page2.html", page_start=25)
    assert second.next_start is None
    sites = merge_sites([first, second])
    assert set(sites) == {"3691", "5001", "5099"}
    assert sites["5099"].site_type == "Campsite Electric"
    assert sites["5099"].nights[date(2026, 12, 28)] == "a"
    assert sites["3691"].site_type == "Campsite Electric"


def test_open_counts_by_type_and_price():
    sites = merge_sites([_page("txparks_page.html"), _page("txparks_page2.html", 25)])
    fees = _page("txparks_page.html").fees
    result = _build_result(
        park_id="1200066",
        park_name="Sample State Park",
        park_slug="sample-state-park",
        park_url="https://example.test/park",
        start=date(2026, 12, 28),
        end=date(2027, 1, 2),
        nights=1,
        sites=sites,
        fees=fees,
        warnings=_coverage_warnings(len(sites), 3),
    )
    by_date = {day.date: day for day in result.days}
    dec28 = by_date[date(2026, 12, 28)]
    assert dec28.total == 3
    assert dec28.available == 2  # cabin + site 099
    electric = next(item for item in dec28.by_type if item.site_type == "Campsite Electric")
    assert electric.available == 1
    assert electric.total == 2
    assert electric.price == "24.00"
    cabin = next(item for item in dec28.by_type if item.site_type == "Cabin")
    assert cabin.available == 1
    assert cabin.price == "86.00"
    assert {site.name for site in dec28.sites} == {"Cabin 1", "099"}

    jan2 = by_date[date(2027, 1, 2)]
    assert jan2.available == 1  # site 099 only
    assert jan2.call_center == 1
    assert jan2.walkup == 0
    assert result.warnings == []


def test_two_night_stay_requires_every_night():
    sites = merge_sites([_page("txparks_page.html"), _page("txparks_page2.html", 25)])
    fees = _page("txparks_page.html").fees
    result = _build_result(
        park_id="1200066",
        park_name="Sample State Park",
        park_slug="sample-state-park",
        park_url="https://example.test/park",
        start=date(2026, 12, 29),
        end=date(2026, 12, 30),
        nights=2,
        sites=sites,
        fees=fees,
        warnings=[],
    )
    by_date = {day.date: day for day in result.days}
    # Site 050 is open Dec 29 and reserved Dec 30, so it is not a two-night arrival.
    assert {site.name for site in by_date[date(2026, 12, 29)].sites} == {"Cabin 1"}
    # Cabin 1 is blocked on Dec 31. Site 099 is open Dec 30 and Dec 31.
    assert {site.name for site in by_date[date(2026, 12, 30)].sites} == {"099"}
    assert _coverage_end(date(2026, 12, 31), 2) == date(2027, 1, 1)


def test_short_page_warns():
    assert "2 of 3" in _coverage_warnings(2, 3)[0]
    assert _coverage_warnings(3, 3) == []
    assert _coverage_warnings(3, None) == []
