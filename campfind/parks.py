"""Parks the owner is likely to check, with ids verified against the live sites.

Texas ids come from the ReserveAmerica directory
(campgroundDirectoryList.do?contractCode=TX&letter=...).
Recreation.gov ids come from /api/search for Army Corps lakes near Austin.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

from campfind.errors import AmbiguousPark, ParkNotFound


@dataclass(frozen=True)
class Park:
    provider: str
    id: str
    slug: str
    name: str
    area: str = ""
    aliases: tuple[str, ...] = ()

    @property
    def keys(self) -> tuple[str, ...]:
        return (self.slug, self.id, _normalize(self.name), *self.aliases)


TEXAS_PARKS: tuple[Park, ...] = (
    Park(
        "txparks",
        "1200066",
        "mckinney-falls-state-park",
        "McKinney Falls State Park",
        "Austin",
        ("mckinney-falls", "mckinney"),
    ),
    Park(
        "txparks",
        "1200068",
        "pedernales-falls-state-park",
        "Pedernales Falls State Park",
        "Hill Country",
        ("pedernales-falls", "pedernales"),
    ),
    Park(
        "txparks",
        "1200062",
        "inks-lake-state-park",
        "Inks Lake State Park",
        "Highland Lakes",
        ("inks-lake", "inks"),
    ),
    Park(
        "txparks",
        "1200052",
        "bastrop-state-park",
        "Bastrop State Park",
        "Bastrop",
        ("bastrop",),
    ),
    Park(
        "txparks",
        "1200059",
        "guadalupe-river-state-park",
        "Guadalupe River State Park",
        "Hill Country",
        ("guadalupe-river", "guadalupe"),
    ),
    Park(
        "txparks",
        "1200056",
        "enchanted-rock-state-natural-area",
        "Enchanted Rock State Natural Area",
        "Hill Country",
        ("enchanted-rock", "enchanted"),
    ),
)

# Army Corps of Engineers campgrounds on Recreation.gov, closest lakes to Austin.
RECGOV_PARKS: tuple[Park, ...] = (
    Park(
        "recgov",
        "232544",
        "cedar-breaks",
        "Cedar Breaks Park",
        "Georgetown Lake",
        ("cedar-breaks-park",),
    ),
    Park(
        "recgov",
        "232612",
        "jim-hogg",
        "Jim Hogg Park",
        "Georgetown Lake",
        ("jim-hogg-park",),
    ),
    Park(
        "recgov",
        "234643",
        "tejas",
        "Tejas Park",
        "Georgetown Lake",
        ("tejas-park",),
    ),
    Park(
        "recgov",
        "234665",
        "russell",
        "Russell Park",
        "Georgetown Lake",
        ("russell-park",),
    ),
    Park(
        "recgov",
        "232718",
        "taylor",
        "Taylor Park",
        "Granger Lake",
        ("taylor-park",),
    ),
    Park(
        "recgov",
        "232748",
        "wilson-h-fox",
        "Wilson H Fox Park",
        "Granger Lake",
        ("wilson-fox", "wilson-h-fox-park"),
    ),
    Park(
        "recgov",
        "232745",
        "willis-creek",
        "Willis Creek Park",
        "Granger Lake",
        ("willis-creek-park",),
    ),
    Park(
        "recgov",
        "233383",
        "friendship",
        "Friendship Park",
        "Granger Lake",
        ("friendship-park",),
    ),
)


def parks_for(provider: str) -> tuple[Park, ...]:
    if provider == "txparks":
        return TEXAS_PARKS
    if provider == "recgov":
        return RECGOV_PARKS
    raise ParkNotFound(f"Unknown provider '{provider}'")


def resolve_builtin(provider: str, query: str) -> Park:
    """Match a built-in park. Raises if the name is missing or ambiguous."""
    parks = parks_for(provider)
    try:
        return match_parks(query, parks)
    except ParkNotFound:
        known = ", ".join(park.aliases[0] if park.aliases else park.slug for park in parks)
        raise ParkNotFound(
            f"No built-in {provider} park matches '{query}'. Known: {known}"
        ) from None


def match_parks(query: str, parks: Sequence[Park]) -> Park:
    """Exact slug, id, or name wins. Otherwise one unique partial match."""
    needle = _normalize(query)
    if not needle:
        raise ParkNotFound("Park name is empty")
    exact = [park for park in parks if needle in {_normalize(key) for key in park.keys}]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise AmbiguousPark(query, [park.name for park in exact])
    partial = [
        park
        for park in parks
        if any(needle in _normalize(key) for key in park.keys)
    ]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        raise AmbiguousPark(query, [park.name for park in partial])
    raise ParkNotFound(f"No park matches '{query}'")


def _normalize(value: str) -> str:
    cleaned = []
    last_dash = False
    for char in value.lower():
        if char.isalnum():
            cleaned.append(char)
            last_dash = False
        elif not last_dash:
            cleaned.append("-")
            last_dash = True
    return "".join(cleaned).strip("-")
