"""CLI, park names, cache, and the polite HTTP client."""

from datetime import date

import pytest

from campfind.cli import main
from campfind.errors import AmbiguousPark, CampfindError, ParkNotFound
from campfind.format import format_json, format_table
from campfind.http import PoliteClient, ResultCache
from campfind.parks import resolve_builtin
from campfind.search import result_from_dict, search
from campfind.tx_html import parse_page
from campfind.txparks import _build_result
from pathlib import Path


def test_builtin_names_and_ids():
    park = resolve_builtin("txparks", "mckinney-falls")
    assert park.id == "1200066"
    assert resolve_builtin("txparks", "1200062").name.startswith("Inks")
    assert resolve_builtin("txparks", "enchanted").id == "1200056"
    assert resolve_builtin("txparks", "guadalupe river").slug == "guadalupe-river-state-park"
    assert resolve_builtin("recgov", "cedar-breaks").id == "232544"
    assert resolve_builtin("recgov", "wilson fox").area == "Granger Lake"
    with pytest.raises(AmbiguousPark):
        resolve_builtin("txparks", "falls")
    with pytest.raises(ParkNotFound):
        resolve_builtin("txparks", "not-a-real-park")


def test_list_command(capsys):
    assert main(["txparks", "--list"]) == 0
    output = capsys.readouterr().out
    assert "1200066" in output
    assert "mckinney-falls" in output
    assert "pedernales" in output
    assert main(["recgov", "--list"]) == 0
    recgov = capsys.readouterr().out
    assert "232544" in recgov
    assert "Georgetown Lake" in recgov


def test_missing_date_is_an_error(capsys):
    assert main(["txparks", "mckinney-falls"]) == 2
    assert "--from" in capsys.readouterr().err


def test_table_and_json_round_trip():
    html = Path("tests/fixtures/txparks_page.html").read_text(encoding="utf-8")
    page = parse_page(html, date(2026, 12, 28))
    result = _build_result(
        park_id="1200066",
        park_name=page.park_name,
        park_slug=page.slug,
        park_url="https://texasstateparks.reserveamerica.com/example",
        start=date(2026, 12, 28),
        end=date(2026, 12, 29),
        nights=1,
        sites=page.sites,
        fees=page.fees,
        warnings=[],
    )
    table = format_table(result)
    assert "Sample State Park" in table
    assert "2026-12-28" in table
    assert "$24.00" in table
    assert "does not reserve" in table
    restored = result_from_dict(__import__("json").loads(format_json(result)))
    assert restored.days[0].available == result.days[0].available
    assert restored.days[0].sites[0].price == result.days[0].sites[0].price
    assert restored.park_id == "1200066"


def test_search_rejects_bad_ranges(tmp_path):
    cache = ResultCache(tmp_path, ttl=0)
    with pytest.raises(CampfindError):
        search("txparks", "mckinney-falls", date(2026, 12, 4), nights=0, cache=cache)
    with pytest.raises(CampfindError):
        search("txparks", "mckinney-falls", date(2026, 12, 4), weeks=9, cache=cache)
    with pytest.raises(CampfindError):
        search(
            "txparks",
            "mckinney-falls",
            date(2026, 12, 4),
            end=date(2026, 12, 1),
            cache=cache,
        )


def test_cache_round_trip(tmp_path):
    cache = ResultCache(tmp_path, ttl=600)
    cache.put("lookup", {"ok": True})
    assert cache.get("lookup") == {"ok": True}
    cache.ttl = 0
    assert cache.get("lookup") is None


class _Response:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload


class _Session:
    def __init__(self, codes):
        self.codes = list(codes)
        self.calls = 0
        self.headers = {}

    def request(self, method, url, timeout=None, **kwargs):
        self.calls += 1
        code = self.codes.pop(0)
        if code == "boom":
            import requests

            raise requests.ConnectionError("nope")
        return _Response(code)


def test_client_does_not_advertise_python_requests():
    client = PoliteClient(min_interval=0, session=_Session([]))
    agent = client.session.headers["User-Agent"]
    assert "python-requests" not in agent.lower()
    assert agent.startswith("Mozilla/5.0")


def test_retries_then_succeeds():
    clock = {"now": 0.0}

    def monotonic():
        return clock["now"]

    def sleep(seconds):
        clock["now"] += seconds

    session = _Session([500, "boom", 200])
    client = PoliteClient(
        min_interval=1,
        attempts=4,
        sleep=sleep,
        clock=monotonic,
        session=session,
    )
    response = client.get("https://example.test/grid")
    assert response.status_code == 200
    assert session.calls == 3
    assert clock["now"] >= 2


def test_http_error_has_no_partial_success():
    client = PoliteClient(min_interval=0, attempts=1, session=_Session([404]))
    with pytest.raises(CampfindError, match="404"):
        client.get("https://example.test/missing")


def test_source_has_no_payment_flow():
    text = "\n".join(path.read_text(encoding="utf-8") for path in Path("campfind").rglob("*.py"))
    assert "credit_card" not in text
    assert "cardnum" not in text
    assert "selenium" not in text.lower()
