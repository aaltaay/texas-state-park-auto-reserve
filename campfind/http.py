"""HTTP session with a slow pace, retries, and a short disk cache."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Callable

import requests

from campfind.errors import CampfindError

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
RETRY_STATUS = {429, 500, 502, 503, 504}


class PoliteClient:
    """One shared client for a lookup.

    Requests to the same process are spaced out. Failed responses are retried
    with exponential backoff. There is no captcha handling.
    """

    def __init__(
        self,
        min_interval: float = 1.1,
        attempts: int = 4,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        session: requests.Session | None = None,
    ):
        self.min_interval = min_interval
        self.attempts = attempts
        self.sleep = sleep
        self.clock = clock
        self.session = session or requests.Session()
        # Session() already sets a python-requests user agent. Replace it.
        # Recreation.gov rejects that default agent.
        self.session.headers["User-Agent"] = USER_AGENT
        self.session.headers["Accept-Language"] = "en-US,en;q=0.9"
        self._last = 0.0

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        timeout = kwargs.pop("timeout", 40)
        delay = 0.8
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            self._pace()
            try:
                response = self.session.request(method, url, timeout=timeout, **kwargs)
            except requests.RequestException as exc:
                last_error = exc
                if attempt + 1 == self.attempts:
                    break
                self.sleep(delay)
                delay *= 2
                continue
            if response.status_code in RETRY_STATUS and attempt + 1 < self.attempts:
                self.sleep(delay)
                delay *= 2
                continue
            if response.status_code >= 400:
                raise CampfindError(
                    f"{method} {url} returned HTTP {response.status_code}"
                )
            return response
        raise CampfindError(f"{method} {url} failed: {last_error}")

    def get(self, url: str, **kwargs) -> requests.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        return self.request("POST", url, **kwargs)

    def get_json(self, url: str, **kwargs) -> dict:
        headers = {"Accept": "application/json"}
        headers.update(kwargs.pop("headers", {}) or {})
        response = self.get(url, headers=headers, **kwargs)
        try:
            payload = response.json()
        except ValueError as exc:
            raise CampfindError(f"Expected JSON from {url}") from exc
        if not isinstance(payload, dict):
            raise CampfindError(f"Expected a JSON object from {url}")
        return payload

    def _pace(self) -> None:
        if self._last:
            wait = self.min_interval - (self.clock() - self._last)
            if wait > 0:
                self.sleep(wait)
        self._last = self.clock()


class ResultCache:
    """Remember a finished lookup for a few minutes."""

    def __init__(
        self,
        directory: Path | None = None,
        ttl: float = 600,
        clock: Callable[[], float] = time.time,
    ):
        self.directory = directory or default_cache_dir()
        self.ttl = ttl
        self.clock = clock

    def get(self, key: str) -> dict | None:
        if self.ttl <= 0:
            return None
        path = self._path(key)
        if not path.exists():
            return None
        age = self.clock() - path.stat().st_mtime
        if age > self.ttl:
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def put(self, key: str, payload: dict) -> None:
        if self.ttl <= 0:
            return
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.directory / f"{digest}.json"


def default_cache_dir() -> Path:
    return Path.home() / ".cache" / "campfind"


def cache_key(provider: str, park_id: str, start: str, end: str, nights: int) -> str:
    return f"{provider}|{park_id}|{start}|{end}|{nights}"
