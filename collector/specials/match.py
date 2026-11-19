"""Dedupe / merge: one record per special."""

from __future__ import annotations

import datetime as dt
from difflib import SequenceMatcher

from .classify import runtime_format
from .ids import special_id
from .platforms import FREE_KINDS
from .store import ID_KEYS
from .titles import match_key
from .util import iso, parse_iso_date


def title_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ratio = SequenceMatcher(None, a, b).ratio()
    ta, tb = set(a.split()), set(b.split())
    jacc = len(ta & tb) / len(ta | tb) if ta | tb else 0.0
    contained = 0.75 if (f" {a} " in f" {b} " or f" {b} " in f" {a} ") else 0.0
    return max(ratio, jacc, contained)


class Matcher:
    def __init__(self, specials: dict[str, dict], names: dict[str, str], scope: dict):
        self.specials = specials
        self.names = names            # slug -> display name
        m = scope.get("match") or {}
        self.window = int(m.get("date_window_days", 45))
        self.strong = float(m.get("strong_title_similarity", 0.92))
        self.partial = float(m.get("partial_title_similarity", 0.6))
        self.rebuild()

    def rebuild(self) -> None:
        self.by_ext: dict[str, str] = {}
        self.by_performer: dict[str, set[str]] = {}
        for sid, s in self.specials.items():
            self.index(s)

    def index(self, s: dict) -> None:
        for k in ("tmdb", "imdb", "youtube"):
            v = (s.get("ids") or {}).get(k)
            if v:
                self.by_ext[f"{k}:{v}"] = s["id"]
        for alt in s.get("alt_ids") or []:
            self.by_ext[alt] = s["id"]
        for p in (s.get("platforms") or []):
            if p.get("platform") == "youtube" and p.get("url") and "v=" in p["url"]:
                self.by_ext[f"youtube:{p['url'].split('v=')[1][:11]}"] = s["id"]
        for p in s.get("performers") or []:
            self.by_performer.setdefault(p, set()).add(s["id"])

    def key(self, title: str, performers: list[str]) -> str:
        return match_key(title, [self.names.get(p, p) for p in performers])

    def find(self, c: dict) -> tuple[str | None, str | None, float]:
        """(special id, 'id' | 'strong' | 'partial' | None, similarity)."""
        for k in ("tmdb", "imdb", "youtube"):
            v = (c.get("ids") or {}).get(k)
            if v and f"{k}:{v}" in self.by_ext:
                return self.by_ext[f"{k}:{v}"], "id", 1.0
        pool: set[str] = set()
        for p in c.get("performers") or []:
            pool |= self.by_performer.get(p, set())
        if not pool:
            return None, None, 0.0
        ck = self.key(c.get("title") or "", c.get("performers") or [])
        cd = parse_iso_date(c.get("release_date"))
        best: tuple[str | None, str | None, float] = (None, None, 0.0)
        for sid in pool:
            s = self.specials[sid]
            sim = title_similarity(ck, self.key(s.get("title") or "", s.get("performers") or []))
            dates = [parse_iso_date(x) for x in (s.get("release_date"), s.get("public_release_date"))]
            dates += [parse_iso_date(p.get("date")) for p in s.get("platforms") or []]
            dates = [d for d in dates if d]
            if cd and dates:
                close = min(abs((cd - d).days) for d in dates) <= self.window
            else:
                close = None   # unknown
            if sim >= self.strong:
                strength = "strong" if close in (True, None) else "partial"
            elif sim >= self.partial and close in (True, None):
                strength = "partial"
            else:
                continue
            rank = (2 if strength == "strong" else 1, sim)
            best_rank = (2 if best[1] == "strong" else 1 if best[1] else 0, best[2])
            if rank > best_rank:
                best = (sid, strength, sim)
        return best


def new_special(c: dict, taken: dict, today: dt.date) -> dict:
    sid = special_id(c.get("performers") or [], c.get("title") or "untitled", c.get("release_date"), taken)
    s = {
        "id": sid,
        "title": c.get("title") or c.get("raw_title") or "Untitled",
        "performers": list(c.get("performers") or []),
        "status": None,
        "format": None,
        "runtime_min": c.get("runtime_min"),
        "language": c.get("language"),
        "release_date": c.get("release_date"),
        "public_release_date": None,
        "platforms": [],
        "ids": {k: None for k in ID_KEYS},
        "sources": [],
        "first_seen": iso(today),
        "updated": iso(today),
    }
    merge_into(s, c)
    return s


def merge_into(s: dict, c: dict) -> None:
    """Fold a candidate (or another special) into special s."""
    for p in c.get("performers") or []:
        if p not in s["performers"]:
            s["performers"].append(p)
    if not s.get("runtime_min") and c.get("runtime_min"):
        s["runtime_min"] = c["runtime_min"]
    elif c.get("source") == "tmdb" and c.get("runtime_min"):
        s["runtime_min"] = c["runtime_min"]         # TMDB runtimes beat everything else
    if not s.get("language") and c.get("language"):
        s["language"] = c["language"]
    ids = s.setdefault("ids", {k: None for k in ID_KEYS})
    for k, v in (c.get("ids") or {}).items():
        if v and not ids.get(k):
            ids[k] = v
        elif v and ids.get(k) != v and k != "wikipedia":
            _add_alt(s, f"{k}:{v}")
    for alt in c.get("alt_ids") or []:
        _add_alt(s, alt)
    for p in c.get("platforms") or []:
        _add_platform(s, p, c.get("release_date"))
    for url in [c.get("url"), *(c.get("sources") or [])]:
        if url and url not in s["sources"]:
            s["sources"].append(url)
    dates = [d for d in (s.get("release_date"), c.get("release_date")) if d]
    if dates:
        s["release_date"] = min(dates)
    if c.get("public_release_date"):
        s["public_release_date"] = c["public_release_date"]


def _add_alt(s: dict, key: str) -> None:
    alts = s.setdefault("alt_ids", [])
    if key not in alts:
        alts.append(key)
        alts.sort()


def _add_platform(s: dict, p: dict, fallback_date: str | None) -> None:
    for existing in s["platforms"]:
        if existing["platform"] == p["platform"] and (
                existing.get("url") == p.get("url") or not existing.get("url") or not p.get("url")):
            if not existing.get("url") and p.get("url"):
                existing["url"] = p["url"]
            if not existing.get("kind"):
                existing["kind"] = p.get("kind")
            d = p.get("date") or fallback_date
            if d and (not existing.get("date") or d < existing["date"]):
                existing["date"] = d
            return
    entry = {"platform": p["platform"], "kind": p.get("kind"), "url": p.get("url")}
    if p.get("date") or (fallback_date and p["platform"] == "youtube"):
        entry["date"] = p.get("date") or fallback_date
    s["platforms"].append(entry)


def derive(s: dict, scope: dict, today: dt.date) -> None:
    """Recompute status, format and public_release_date from the record's facts."""
    pdates = [p["date"] for p in s.get("platforms") or [] if p.get("date")]
    if pdates:
        earliest = min(pdates)
        if not s.get("release_date") or earliest < s["release_date"]:
            s["release_date"] = earliest
    free = [p["date"] for p in s.get("platforms") or [] if p.get("kind") in FREE_KINDS and p.get("date")]
    paid_first = [p for p in s.get("platforms") or [] if p.get("kind") not in FREE_KINDS]
    if free and paid_first and s.get("release_date") and min(free) > s["release_date"]:
        s["public_release_date"] = min(free)
    elif not s.get("public_release_date") or (s.get("release_date") and
                                              s["public_release_date"] <= s["release_date"]):
        s["public_release_date"] = None
    rd = parse_iso_date(s.get("release_date"))
    s["status"] = "announced" if not rd else ("upcoming" if rd > today else "released")
    fmt = runtime_format(s.get("runtime_min"), scope)
    if fmt:
        s["format"] = fmt
    s["platforms"].sort(key=lambda p: (p.get("date") or "9999", p["platform"]))
