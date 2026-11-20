"""Turn a lookup into text or JSON."""

from __future__ import annotations

import json

from campfind.models import AvailabilityResult, DayAvailability
from campfind.money import price_label


def format_json(result: AvailabilityResult) -> str:
    return json.dumps(result.to_dict(), indent=2)


def format_table(result: AvailabilityResult) -> str:
    lines = [
        f"{result.park_name}  ({result.provider} {result.park_id})",
        (
            f"{result.nights} night stay. Arrival dates "
            f"{result.start.isoformat()} through {result.end.isoformat()}."
        ),
        result.park_url,
        "",
        _columns(
            ("Date", "Open", "Total", "By type"),
            [_summary_row(day) for day in result.days],
        ),
        "",
        "Open sites",
    ]
    grouped = _grouped_sites(result)
    if grouped:
        lines.append(_columns(("Date", "Type", "Price", "Sites"), grouped))
    else:
        lines.append("None")
    lines.append("")
    lines.append(result.price_note)
    lines.append("Book on the park site. This tool does not reserve or take payment.")
    for warning in result.warnings:
        lines.append(f"Warning: {warning}")
    return "\n".join(lines)


def format_park_list(parks) -> str:
    rows = [(park.aliases[0] if park.aliases else park.slug, park.id, park.area, park.name) for park in parks]
    return _columns(("Name", "Id", "Area", "Full name"), rows)


def _summary_row(day: DayAvailability) -> tuple[str, str, str, str]:
    parts = []
    for item in day.by_type:
        label = price_label(item.price, item.price_max)
        price = f" {label}" if label else ""
        parts.append(f"{item.site_type} {item.available}/{item.total}{price}")
    extra = []
    if day.walkup:
        extra.append(f"{day.walkup} walk-up")
    if day.call_center:
        extra.append(f"{day.call_center} phone-only")
    detail = "; ".join(parts)
    if extra:
        detail = f"{detail} ({', '.join(extra)})" if detail else ", ".join(extra)
    return (
        day.date.strftime("%a %Y-%m-%d"),
        str(day.available),
        str(day.total),
        detail,
    )


def _grouped_sites(result: AvailabilityResult) -> list[tuple[str, str, str, str]]:
    rows = []
    for day in result.days:
        grouped: dict[str, list] = {}
        for site in day.sites:
            grouped.setdefault(site.site_type, []).append(site)
        for site_type, sites in grouped.items():
            first = sites[0]
            names = ", ".join(
                f"{site.name}" + (f" x{site.spots}" if site.spots > 1 else "")
                for site in sites
            )
            rows.append(
                (
                    day.date.isoformat(),
                    site_type,
                    price_label(first.price, first.price_max) or "-",
                    names,
                )
            )
    return rows


def _columns(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    widths = [len(header) for header in headers]
    rendered = [tuple(str(cell) for cell in row) for row in rows]
    for row in rendered:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    def line(row: tuple[str, ...]) -> str:
        return "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row))
    body = [line(headers), line(tuple("-" * width for width in widths))]
    body.extend(line(row) for row in rendered)
    return "\n".join(body)
