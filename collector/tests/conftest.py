import datetime as dt
import json
import shutil
from pathlib import Path
from urllib.parse import urlparse

import pytest

from specials.config import Config, Repo
from specials.store import load_state

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).parent / "fixtures"
TODAY = dt.date(2026, 2, 20)


class FakeHttp:
    """Routes by (host, path) to canned responses. Records calls."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls = []

    def _find(self, url, params):
        u = urlparse(url)
        self.calls.append((u.netloc + u.path, params))
        for key in (u.netloc + u.path, u.path):
            if key in self.routes:
                r = self.routes[key]
                return r(params) if callable(r) else r
        raise AssertionError(f"unexpected request {url} {params}")

    def get_json(self, url, params=None, headers=None):
        return self._find(url, params)

    def get_text(self, url, params=None, headers=None):
        return self._find(url, params)

    def send_json(self, method, url, body, headers=None):
        self.calls.append((method, url, body))
        return {"html_url": "https://github.com/x/y/issues/1", "url": url}


@pytest.fixture
def repo(tmp_path):
    shutil.copytree(ROOT / "config", tmp_path / "config")
    (tmp_path / "data").mkdir()
    d = tmp_path / "data"
    (d / "comedians.yaml").write_text("# Comedians\ncomedians: []\n")
    (d / "overrides.yaml").write_text("# decisions\naccept: []\nreject: []\nmerge: []\nedit: {}\n")
    for name in ("specials.jsonl", "candidates.jsonl"):
        (d / name).write_text("")
    for name in ("redirects.json", "meta.json"):
        (d / name).write_text("{}\n")
    return Repo(tmp_path)


@pytest.fixture
def config(repo):
    return Config.load(repo)


@pytest.fixture
def state(repo):
    return load_state(repo)


def fixture_text(name):
    return (FIX / name).read_text()


def tmdb_movie(mid, title, cast, runtime, release, providers=("Netflix",), keyword=True, lang="en"):
    return {
        "id": mid, "title": title, "runtime": runtime, "release_date": release,
        "original_language": lang,
        "credits": {"cast": [{"name": n, "order": i} for i, n in enumerate(cast)]},
        "external_ids": {"imdb_id": f"tt{mid:07d}"},
        "keywords": {"keywords": [{"id": 9716, "name": "stand-up comedy"}] if keyword else []},
        "release_dates": {"results": [{"iso_3166_1": "US", "release_dates": [{"release_date": release + "T00:00:00.000Z"}]}]},
        "watch/providers": {"results": {"US": {"flatrate": [{"provider_name": p} for p in providers]}}},
    }


def tmdb_routes(movies):
    by_id = {m["id"]: m for m in movies}

    def details(mid):
        return lambda params: by_id[mid]
    routes = {
        "/3/search/keyword": {"results": [{"id": 9716, "name": "stand-up comedy"}]},
        "/3/discover/movie": {"total_pages": 1, "results": [{"id": m["id"]} for m in movies]},
    }
    for mid in by_id:
        routes[f"/3/movie/{mid}"] = details(mid)
    return routes


def wiki_routes(html_by_year):
    def parse(params):
        year = int(params["page"][:4])
        if year not in html_by_year:
            return {"error": {"info": "missing"}}
        return {"parse": {"text": html_by_year[year]}}
    return {"/w/api.php": parse}


ENV = {"TMDB_READ_TOKEN": "x", "YOUTUBE_API_KEY": "y"}


def dumps(o):
    return json.dumps(o, indent=1)
