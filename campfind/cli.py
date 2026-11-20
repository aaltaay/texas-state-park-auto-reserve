"""Command line for campfind."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone

from campfind.errors import CampfindError
from campfind.format import format_json, format_park_list, format_table
from campfind.http import ResultCache
from campfind.parks import parks_for
from campfind.search import search


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="campfind",
        description="Look up campsite availability. Booking stays on the park website.",
    )
    sub = parser.add_subparsers(dest="provider", required=True)
    for name, help_text in (
        ("txparks", "Texas State Parks (ReserveAmerica)"),
        ("recgov", "Recreation.gov, including Army Corps lakes near Austin"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("park", nargs="?", help="Park name, short name, or id")
        command.add_argument("--list", action="store_true", help="Show built-in parks")
        command.add_argument("--from", dest="start", help="First arrival date, YYYY-MM-DD")
        command.add_argument("--to", dest="end", help="Last arrival date, YYYY-MM-DD")
        command.add_argument("--nights", type=int, default=1, help="Nights per stay (default 1)")
        command.add_argument(
            "--weeks",
            type=int,
            default=None,
            help="Weeks of arrival dates from --from (default 1). Not used with --to.",
        )
        command.add_argument("--json", action="store_true", help="Print JSON instead of a table")
        command.add_argument("--refresh", action="store_true", help="Ignore the cached lookup")
        command.add_argument(
            "--cache-seconds",
            type=float,
            default=600,
            help="How long to reuse a lookup (default 600, 0 to disable)",
        )
    args = parser.parse_args(argv)
    try:
        return _run(args)
    except CampfindError as exc:
        print(exc, file=sys.stderr)
        return 2


def _run(args: argparse.Namespace) -> int:
    if args.list:
        print(format_park_list(parks_for(args.provider)))
        return 0
    if not args.park or not args.start:
        raise CampfindError("Pass a park and --from YYYY-MM-DD. Use --list to see built-in parks.")
    if args.end and args.weeks is not None:
        raise CampfindError("Pass either --to or --weeks, not both.")
    start = _parse_date(args.start, "--from")
    end = _parse_date(args.end, "--to") if args.end else None
    result = search(
        args.provider,
        args.park,
        start,
        nights=args.nights,
        end=end,
        weeks=args.weeks,
        cache=ResultCache(ttl=args.cache_seconds),
        refresh=args.refresh,
    )
    age = datetime.now(timezone.utc) - result.fetched_at
    if age.total_seconds() > 20:
        stamp = result.fetched_at.strftime("%Y-%m-%d %H:%M UTC")
        print(f"Cached lookup from {stamp}. Pass --refresh for a live check.", file=sys.stderr)
    print(format_json(result) if args.json else format_table(result))
    return 0


def _parse_date(value: str, flag: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CampfindError(f"{flag} must be YYYY-MM-DD") from exc
