"""HTTP client with retries. Tests swap in a fake with the same methods."""

from __future__ import annotations

import time
from typing import Any

import requests

from . import __version__


class HttpError(RuntimeError):
    def __init__(self, status: int, url: str, body: str = ""):
        super().__init__(f"HTTP {status} for {url}: {body[:200]}")
        self.status = status


class Http:
    def __init__(self, user_agent: str | None = None, timeout: float = 30, retries: int = 3):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = user_agent or (
            f"specials-tracker/{__version__} (personal non-commercial project)")
        self.timeout = timeout
        self.retries = retries

    def request(self, method: str, url: str, **kw) -> requests.Response:
        delay = 2.0
        for attempt in range(self.retries + 1):
            try:
                r = self.s.request(method, url, timeout=self.timeout, **kw)
            except requests.RequestException:
                if attempt == self.retries:
                    raise
                time.sleep(delay)
                delay *= 2
                continue
            if r.status_code in (429, 500, 502, 503, 504) and attempt < self.retries:
                time.sleep(float(r.headers.get("Retry-After") or delay))
                delay *= 2
                continue
            if r.status_code >= 400:
                raise HttpError(r.status_code, url, r.text)
            return r
        raise RuntimeError("unreachable")

    def get_json(self, url: str, params: dict | None = None, headers: dict | None = None) -> Any:
        return self.request("GET", url, params=params, headers=headers).json()

    def get_text(self, url: str, params: dict | None = None, headers: dict | None = None) -> str:
        return self.request("GET", url, params=params, headers=headers).text

    def send_json(self, method: str, url: str, body: dict, headers: dict | None = None) -> Any:
        r = self.request(method, url, json=body, headers=headers)
        return r.json() if r.content else None
