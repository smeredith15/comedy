"""Reading and writing the data/ files, plus the SQLite working cache.

Git is the database: specials.jsonl and candidates.jsonl are sorted, one record
per line, so each nightly commit diff shows exactly what changed. SQLite is only
a local cache for ad-hoc queries (data/cache.sqlite, git-ignored).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .config import Repo, dump_yaml, load_yaml

SPECIAL_FIELDS = [
    "id", "title", "performers", "status", "format", "runtime_min", "language",
    "release_date", "public_release_date", "platforms", "ids", "alt_ids", "sources",
    "hidden", "first_seen", "updated",
]
CANDIDATE_FIELDS = [
    "id", "source", "source_key", "title", "raw_title", "performers", "performer_names",
    "release_date", "runtime_min", "language", "platforms", "ids", "url", "channel",
    "evidence", "showcase", "trusted", "reasons", "match", "first_seen", "updated",
]
ID_KEYS = ["tmdb", "imdb", "youtube", "wikipedia"]


def ordered(rec: dict, fields: list[str]) -> dict:
    out = {k: rec[k] for k in fields if k in rec}
    out.update({k: v for k, v in rec.items() if k not in out})
    return out


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def write_jsonl(path: Path, records: list[dict], fields: list[str]) -> None:
    lines = [json.dumps(ordered(r, fields), ensure_ascii=False)
             for r in sorted(records, key=lambda r: r["id"])]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists() or not path.read_text().strip():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                    encoding="utf-8")


@dataclass
class State:
    repo: Repo
    comedians_doc: CommentedMap
    specials: dict[str, dict] = field(default_factory=dict)
    candidates: dict[str, dict] = field(default_factory=dict)
    overrides: CommentedMap = field(default_factory=CommentedMap)
    redirects: dict[str, str] = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    @property
    def comedians(self) -> CommentedSeq:
        if self.comedians_doc.get("comedians") is None:
            self.comedians_doc["comedians"] = CommentedSeq()
        return self.comedians_doc["comedians"]

    def comedian(self, slug: str) -> dict | None:
        return next((c for c in self.comedians if c.get("slug") == slug), None)

    def resolve_id(self, special_id: str) -> str:
        seen = set()
        while special_id in self.redirects and special_id not in seen:
            seen.add(special_id)
            special_id = self.redirects[special_id]
        return special_id

    def override_list(self, key: str) -> list:
        val = self.overrides.get(key)
        return list(val) if val else []


def load_state(repo: Repo) -> State:
    d = repo.data
    comedians_doc = load_yaml(d / "comedians.yaml") or CommentedMap()
    overrides = load_yaml(d / "overrides.yaml") or CommentedMap()
    for k, default in (("accept", []), ("reject", []), ("merge", []), ("edit", {})):
        if overrides.get(k) is None:
            overrides[k] = CommentedSeq() if isinstance(default, list) else CommentedMap()
    return State(
        repo=repo,
        comedians_doc=comedians_doc,
        specials={r["id"]: r for r in read_jsonl(d / "specials.jsonl")},
        candidates={r["id"]: r for r in read_jsonl(d / "candidates.jsonl")},
        overrides=overrides,
        redirects=read_json(d / "redirects.json", {}),
        meta=read_json(d / "meta.json", {}),
    )


def save_state(state: State, *, overrides: bool = False) -> None:
    d = state.repo.data
    d.mkdir(parents=True, exist_ok=True)
    state.comedians.sort(key=lambda c: c.get("slug", ""))
    dump_yaml(d / "comedians.yaml", state.comedians_doc)
    write_jsonl(d / "specials.jsonl", list(state.specials.values()), SPECIAL_FIELDS)
    write_jsonl(d / "candidates.jsonl", list(state.candidates.values()), CANDIDATE_FIELDS)
    write_json(d / "redirects.json", state.redirects)
    write_json(d / "meta.json", state.meta)
    if overrides:
        dump_yaml(d / "overrides.yaml", state.overrides)


def save_overrides(state: State) -> None:
    dump_yaml(state.repo.data / "overrides.yaml", state.overrides)


def build_sqlite(state: State, path: Path | None = None) -> Path:
    """Rebuild the git-ignored SQLite cache from the text files."""
    path = path or state.repo.data / "cache.sqlite"
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE specials (id TEXT PRIMARY KEY, title TEXT, status TEXT, format TEXT,
            runtime_min INTEGER, language TEXT, release_date TEXT, public_release_date TEXT,
            hidden INTEGER, first_seen TEXT, updated TEXT, tmdb TEXT, imdb TEXT, youtube TEXT, json TEXT);
        CREATE TABLE special_performers (special_id TEXT, performer TEXT, position INTEGER);
        CREATE TABLE special_platforms (special_id TEXT, platform TEXT, kind TEXT, url TEXT, date TEXT);
        CREATE TABLE comedians (slug TEXT PRIMARY KEY, name TEXT, tracked INTEGER, followed INTEGER,
            tmdb_id INTEGER, youtube_channel_id TEXT);
        CREATE TABLE candidates (id TEXT PRIMARY KEY, source TEXT, title TEXT, release_date TEXT,
            runtime_min INTEGER, match TEXT, reasons TEXT, json TEXT);
        CREATE TABLE redirects (old_id TEXT PRIMARY KEY, new_id TEXT);
    """)
    for s in state.specials.values():
        ids = s.get("ids") or {}
        con.execute("INSERT INTO specials VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            s["id"], s.get("title"), s.get("status"), s.get("format"), s.get("runtime_min"),
            s.get("language"), s.get("release_date"), s.get("public_release_date"),
            int(bool(s.get("hidden"))), s.get("first_seen"), s.get("updated"),
            ids.get("tmdb"), ids.get("imdb"), ids.get("youtube"), json.dumps(s)))
        for i, p in enumerate(s.get("performers") or []):
            con.execute("INSERT INTO special_performers VALUES (?,?,?)", (s["id"], p, i))
        for p in s.get("platforms") or []:
            con.execute("INSERT INTO special_platforms VALUES (?,?,?,?,?)",
                        (s["id"], p.get("platform"), p.get("kind"), p.get("url"), p.get("date")))
    for c in state.comedians:
        con.execute("INSERT OR REPLACE INTO comedians VALUES (?,?,?,?,?,?)", (
            c.get("slug"), c.get("name"), int(bool(c.get("tracked"))), int(bool(c.get("followed"))),
            c.get("tmdb_id"), c.get("youtube_channel_id")))
    for c in state.candidates.values():
        con.execute("INSERT INTO candidates VALUES (?,?,?,?,?,?,?,?)", (
            c["id"], c.get("source"), c.get("title"), c.get("release_date"), c.get("runtime_min"),
            c.get("match"), "; ".join(c.get("reasons") or []), json.dumps(c)))
    con.executemany("INSERT INTO redirects VALUES (?,?)", list(state.redirects.items()))
    con.commit()
    con.close()
    return path
