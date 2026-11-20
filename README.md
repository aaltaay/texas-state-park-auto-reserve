# campfind

Look up which campsites are open. You pick a park and the dates. campfind prints how many sites are open each day, and which sites those are.

It does not book anything. You still reserve on the park website.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
campfind txparks mckinney-falls --from 2026-12-04 --nights 1 --weeks 4
```

Add `--json` for the same lookup as JSON.

```bash
campfind txparks mckinney-falls --from 2026-12-04 --nights 1 --weeks 4 --json
campfind recgov cedar-breaks --from 2026-12-04 --nights 2 --weeks 1
campfind txparks --list
campfind recgov --list
```

From Python:

```python
from datetime import date
from campfind import search

result = search("txparks", "mckinney-falls", date(2026, 12, 4), nights=1, weeks=4)
print(result.days[0].available, result.days[0].total)
```

## How to read the table

`Open` means you can book that arrival online. `--nights 2` means the site is free for the whole stay, not just the first night.

`Total` is how many sites of that kind the grid listed. A Saturday that reads `0` open and `82` total is full for online booking.

`walk-up` and `phone-only` are shown when the park marks a site that way. Those are not counted as open.

The price is the published nightly rate for that site type. It is not a checkout quote.

## Parks near Austin

Texas State Parks, checked against the live park directory:

| Name you can type | Park | Id |
| --- | --- | --- |
| mckinney-falls | McKinney Falls State Park | 1200066 |
| pedernales-falls | Pedernales Falls State Park | 1200068 |
| inks-lake | Inks Lake State Park | 1200062 |
| bastrop | Bastrop State Park | 1200052 |
| guadalupe-river | Guadalupe River State Park | 1200059 |
| enchanted-rock | Enchanted Rock State Natural Area | 1200056 |

Other Texas parks work by full name (`campfind txparks "Garner State Park" --from 2026-12-04`). The tool reads that name from the public park directory.

Recreation.gov campgrounds on Army Corps lakes near Austin:

| Name you can type | Park | Lake | Id |
| --- | --- | --- | --- |
| cedar-breaks | Cedar Breaks Park | Georgetown Lake | 232544 |
| jim-hogg | Jim Hogg Park | Georgetown Lake | 232612 |
| tejas | Tejas Park | Georgetown Lake | 234643 |
| russell | Russell Park | Georgetown Lake | 234665 |
| taylor | Taylor Park | Granger Lake | 232718 |
| wilson-h-fox | Wilson H Fox Park | Granger Lake | 232748 |
| willis-creek | Willis Creek Park | Granger Lake | 232745 |
| friendship | Friendship Park | Granger Lake | 233383 |

You can also pass a Recreation.gov facility id, or a campground name. If several campgrounds match, campfind lists them and stops.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

HTML and JSON fixtures live in `tests/fixtures/`. They are trimmed copies of the real page and API shapes. `pytest` does not call the parks.

## Where the ideas came from

This repo used to be a Selenium script that logged in and paid for a site. That is gone, including the credit card config. Booking stays manual.

Ideas, not copied code:

- [juftin/camply](https://github.com/juftin/camply) (MIT). Separate providers, a small HTTP client with backoff, and Recreation.gov's month grid at `/api/camps/availability/campground/{id}/month`. No camply code is included here.
- [flexyford/texas-state-park-reservations-api](https://github.com/flexyford/texas-state-park-reservations-api) and [flexyford/tx-state-park-reservations](https://github.com/flexyford/tx-state-park-reservations). No license file. Last push in 2017, against the old reserveworld site. The useful idea was a park list plus per-day counts by site type. None of that code is included.
- The old script in this repo showed which ReserveAmerica pages a person clicks. The lookup itself is plain HTTP against the pages the site renders without a login.

## Limits

- Texas availability is HTML. The first page is `campgroundDetails.do` (a normal search). If the park has more than 25 sites, the next pages are the same `campsitePaging.do` request the website makes. ReserveAmerica's robots.txt asks crawlers not to hit that path. campfind only does it for the one park you asked about, about one request a second, and it caches the result for 10 minutes. Pass `--refresh` to look again. Pass `--cache-seconds 0` to skip the cache.
- No login, no captcha solving, and no headless browser. If the park page starts requiring one, this tool will fail instead of trying to get around it.
- A Texas lookup of 4 weeks is two 14-day grids. `--weeks` can be 1 to 8. `--nights` can be 1 to 14.
- The Texas price is the rate table on the park page (by site type). The page says that price skips discounts, entrance fees, and taxes.
- Recreation.gov prices show up only when their rates feed has a season that covers your date. A lot of seasons in that feed are old. When none cover the date, the price is empty.
- Counts change all day. A full Saturday can open up when someone cancels. This tool does not hold the site for you.
