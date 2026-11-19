"""JSON export for the app: app/public/data/db.json."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

from .config import Config
from .store import State

SPECIAL_KEYS = ["id", "title", "performers", "status", "format", "runtime_min", "release_date",
                "public_release_date", "platforms", "ids", "first_seen"]


def build(state: State, config: Config) -> dict:
    specials = []
    performers: set[str] = set()
    for s in state.specials.values():
        if s.get("hidden"):
            continue
        rec = {k: s.get(k) for k in SPECIAL_KEYS if s.get(k) not in (None, [], {})}
        rec["ids"] = {k: v for k, v in (s.get("ids") or {}).items() if v}
        rec["platforms"] = [{k: v for k, v in p.items() if v} for p in s.get("platforms") or []]
        specials.append(rec)
        performers.update(s.get("performers") or [])
    specials.sort(key=lambda r: (r.get("release_date") or "9999-99-99", r["id"]), reverse=True)

    comedians = {}
    for c in state.comedians:
        slug = c.get("slug")
        if slug in performers or c.get("followed"):
            comedians[slug] = {"name": c.get("name")} | ({"followed": True} if c.get("followed") else {})
    for slug in performers - comedians.keys():
        comedians[slug] = {"name": slug.replace("-", " ").title()}

    platforms = {}
    used = {p["platform"] for s in specials for p in s.get("platforms", [])}
    for slug, info in (config.platforms or {}).items():
        platforms[slug] = {k: info[k] for k in ("name", "kind", "color", "search_url") if info.get(k)}
    for slug in used - platforms.keys():
        platforms[slug] = {"name": slug.replace("-", " ").title()}

    meta = state.meta or {}
    return {
        "version": 1,
        "generated": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "last_run": meta.get("last_run"),
        "repo": os.environ.get("GITHUB_REPOSITORY") or None,
        "region": config.scope.get("region", "US"),
        "counts": meta.get("counts") or {},
        "specials": specials,
        "comedians": dict(sorted(comedians.items())),
        "platforms": platforms,
        "redirects": state.redirects,
    }


def write(state: State, config: Config, out_dir: Path | None = None) -> Path:
    out_dir = out_dir or state.repo.app_data
    out_dir.mkdir(parents=True, exist_ok=True)
    data = build(state, config)
    path = out_dir / "db.json"
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (out_dir / "version.json").write_text(json.dumps({"generated": data["generated"],
                                                      "count": len(data["specials"])}), encoding="utf-8")
    return path
