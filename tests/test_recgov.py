"""Recreation.gov month-grid tests, using a saved JSON fixture."""

import json
from datetime import date
from pathlib import Path

from campfind.parks import Park
from campfind.recgov import _absorb, _build_result, _months

FIXTURES = Path(__file__).parent / "fixtures"


def _payload():
    return json.loads((FIXTURES / "recgov_month.json").read_text(encoding="utf-8"))


def _rates():
    return json.loads((FIXTURES / "recgov_rates.json").read_text(encoding="utf-8"))["rates_list"]


def test_one_night_and_two_night_stays():
    store = {}
    _absorb(store, _payload()["campsites"])
    park = Park("recgov", "232544", "cedar-breaks", "Cedar Breaks Park", "Georgetown Lake")
    one = _build_result(park, "CEDAR BREAKS PARK", date(2026, 12, 4), date(2026, 12, 7), 1, store, _rates())
    assert one.park_name == "Cedar Breaks Park"
    days = {day.date: day for day in one.days}
    dec4 = days[date(2026, 12, 4)]
    assert dec4.total == 3
    # two site-specific opens plus a group record with 4 spots
    assert dec4.available == 6
    electric = next(item for item in dec4.by_type if item.site_type == "STANDARD ELECTRIC")
    assert electric.available == 1
    assert electric.price == "30.00"
    assert {site.name for site in dec4.sites} == {"062", "063", "GROUP"}
    group = next(site for site in dec4.sites if site.name == "GROUP")
    assert group.spots == 4
    assert group.price is None

    dec5 = days[date(2026, 12, 5)]
    assert {site.name for site in dec5.sites} == {"063", "GROUP"}
    dec6 = days[date(2026, 12, 6)]
    assert {site.name for site in dec6.sites} == {"062", "GROUP"}

    two = _build_result(park, "Cedar Breaks Park", date(2026, 12, 4), date(2026, 12, 6), 2, store, _rates())
    two_days = {day.date: day for day in two.days}
    # 062 is reserved on the 5th. 063 is open the 4th and 5th.
    assert {site.name for site in two_days[date(2026, 12, 4)].sites} == {"063", "GROUP"}
    # 063 is closed on the 6th, so the 5th is not a 2-night arrival for it.
    assert {site.name for site in two_days[date(2026, 12, 5)].sites} == {"GROUP"}
    # 062 is open the 6th and 7th. The group site is reserved on the 7th.
    assert {site.name for site in two_days[date(2026, 12, 6)].sites} == {"062"}


def test_later_month_fills_in_missing_days():
    store = {}
    _absorb(store, _payload()["campsites"])
    _absorb(
        store,
        {
            "26004": {
                "campsite_id": "26004",
                "availabilities": {"2027-01-01T00:00:00Z": "Available"},
            },
            "99901": {
                "quantities": {"2027-01-01T00:00:00Z": 3},
                "availabilities": {"2027-01-01T00:00:00Z": "Available"},
            },
        },
    )
    assert store["26004"]["availabilities"]["2026-12-04T00:00:00Z"] == "Available"
    assert store["26004"]["availabilities"]["2027-01-01T00:00:00Z"] == "Available"
    assert store["26004"]["site"] == "062"
    assert store["99901"]["quantities"]["2026-12-04T00:00:00Z"] == 4
    assert store["99901"]["quantities"]["2027-01-01T00:00:00Z"] == 3


def test_pooled_stay_uses_the_smaller_night():
    park = Park("recgov", "1", "group", "Group", "Lake")
    raw = {
        "campsite_id": "1",
        "site": "GROUP",
        "loop": "GROUP",
        "campsite_reserve_type": "Non Site-Specific",
        "campsite_type": "GROUP",
        "availabilities": {
            "2026-12-04T00:00:00Z": "Available",
            "2026-12-05T00:00:00Z": "Available",
        },
        "quantities": {
            "2026-12-04T00:00:00Z": 4,
            "2026-12-05T00:00:00Z": 1,
        },
    }
    result = _build_result(park, "Group", date(2026, 12, 4), date(2026, 12, 4), 2, {"1": raw}, [])
    assert result.days[0].available == 1
    assert result.days[0].sites[0].spots == 1


def test_month_span_crosses_the_year():
    months = list(_months(date(2026, 12, 4), date(2027, 1, 2)))
    assert months == [date(2026, 12, 1), date(2027, 1, 1)]
