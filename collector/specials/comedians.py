"""Comedian list: import from the seed file, name lookup, and TMDB/YouTube resolution."""

from __future__ import annotations

import re
from pathlib import Path

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .store import State
from .util import iso, norm, parse_iso_date, slugify

SUFFIX_RE = re.compile(r"\s*\((comedy|comedian|comic|stand[- ]?up|humor|humour)\)\s*$", re.I)
GROUP_RE = re.compile(r"(\s&\s|\band\b|\bband\b|\borchestra\b|\btrio\b|\bduo\b|\bquartet\b|\bbrothers\b|\bsisters\b)", re.I)


def new_comedian(name: str, *, tracked: bool, flags: list[str] | None = None) -> CommentedMap:
    c = CommentedMap()
    c["slug"] = slugify(name)
    c["name"] = name
    c["aliases"] = CommentedSeq()
    c["tmdb_id"] = None
    c["youtube_channel_id"] = None
    c["followed"] = False
    c["tracked"] = tracked
    if flags:
        c["flags"] = CommentedSeq(flags)
        c["checked"] = False
    return c


def clean_seed_name(raw: str) -> tuple[str, list[str]]:
    """Strip Pandora suffixes and return (name, flags)."""
    flags: list[str] = []
    name = raw.strip()
    if SUFFIX_RE.search(name):
        name = SUFFIX_RE.sub("", name).strip()
        # Pandora only adds "(Comedy)"-style suffixes to tell an artist apart from
        # someone else with the same name, usually a musician.
        flags.append("name shared with another artist on Pandora (likely a musician)")
    if GROUP_RE.search(name):
        flags.append("looks like a group or band name")
    return " ".join(name.split()), flags


def import_seed(state: State, path: Path) -> dict:
    """Add names from the seed file. Returns counts."""
    existing = {c["slug"] for c in state.comedians}
    added, dupes, flagged = 0, 0, 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, flags = clean_seed_name(line)
        if not name:
            continue
        slug = slugify(name)
        if slug in existing:
            c = state.comedian(slug)
            if c is not None and not c.get("tracked"):
                c["tracked"] = True
            dupes += 1
            continue
        state.comedians.append(new_comedian(name, tracked=True, flags=flags))
        existing.add(slug)
        added += 1
        flagged += bool(flags)
    return {"added": added, "duplicates": dupes, "flagged": flagged}


class NameIndex:
    """Normalized name / alias -> comedian slug."""

    def __init__(self, comedians):
        self.by_name: dict[str, str] = {}
        self.names: dict[str, str] = {}
        for c in comedians:
            slug = c.get("slug")
            if not slug:
                continue
            self.names[slug] = c.get("name", slug)
            for n in [c.get("name", ""), *(c.get("aliases") or [])]:
                if n:
                    self.by_name.setdefault(norm(n), slug)

    def lookup(self, name: str) -> str | None:
        return self.by_name.get(norm(name))

    def find_in(self, text: str) -> list[str]:
        """Known comedian names that appear as whole phrases in text, longest first."""
        t = f" {norm(text)} "
        hits = [(len(n), s) for n, s in self.by_name.items() if len(n) > 3 and f" {n} " in t]
        out: list[str] = []
        for _, s in sorted(hits, reverse=True):
            if s not in out:
                out.append(s)
        return out

    def add(self, slug: str, name: str) -> None:
        self.names.setdefault(slug, name)
        self.by_name.setdefault(norm(name), slug)


def ensure_performers(state: State, names: list[str], index: NameIndex) -> list[str]:
    """Slugs for these names, adding untracked comedians for new names."""
    slugs = []
    for name in names:
        slug = index.lookup(name)
        if not slug:
            slug = slugify(name)
            if state.comedian(slug) is None:
                state.comedians.append(new_comedian(name, tracked=False))
            index.add(slug, name)
        if slug not in slugs:
            slugs.append(slug)
    return slugs


# --- resolution -------------------------------------------------------------

def resolve(state: State, ctx, *, limit: int, retry_after_days: int = 30,
            tmdb_limit: int = 1000) -> dict:
    """Find TMDB person IDs and YouTube channel IDs for tracked comedians.

    TMDB lookups are free, so every tracked comedian is tried each run (up to tmdb_limit).
    YouTube channel searches cost 100 quota units each, so only `limit` run per night.
    """
    from .sources import tmdb, youtube_api

    stats = {"tmdb": 0, "youtube": 0, "needs_review": 0, "tmdb_tried": 0, "youtube_tried": 0}
    today = ctx.today

    def due(c, key: str) -> bool:
        last = parse_iso_date(c.get(key) or c.get("resolve_attempted"))
        return not last or (today - last).days >= retry_after_days

    tracked = [c for c in state.comedians if c.get("tracked")]
    if ctx.env.get("TMDB_READ_TOKEN"):
        for c in [c for c in tracked if not c.get("tmdb_id") and due(c, "tmdb_attempted")][:tmdb_limit]:
            stats["tmdb_tried"] += 1
            pid, note = tmdb.find_person(ctx, c["name"])
            if pid:
                c["tmdb_id"] = pid
                stats["tmdb"] += 1
            _note(c, "tmdb_review", note)
            c["tmdb_attempted"] = iso(today)
    if ctx.env.get("YOUTUBE_API_KEY"):
        for c in [c for c in tracked if not c.get("youtube_channel_id") and due(c, "youtube_attempted")][:limit]:
            stats["youtube_tried"] += 1
            cid, note = youtube_api.find_channel(ctx, c["name"], c.get("youtube_handle"))
            if cid:
                c["youtube_channel_id"] = cid
                stats["youtube"] += 1
            _note(c, "youtube_review", note)
            c["youtube_attempted"] = iso(today)
    for c in tracked:   # tidy up the fields used by the first version
        if c.get("tmdb_attempted") or c.get("youtube_attempted"):
            c.pop("resolve_attempted", None)
        if "tmdb_review" in c or "youtube_review" in c:
            c.pop("needs_review", None)
    stats["needs_review"] = sum(1 for c in tracked if c.get("tmdb_review") or c.get("youtube_review"))
    return stats


def _note(c, key: str, note: str | None) -> None:
    if note:
        c[key] = note
    elif key in c:
        del c[key]


def flagged(state: State) -> list[dict]:
    return [c for c in state.comedians
            if (c.get("flags") and not c.get("checked"))
            or c.get("needs_review") or c.get("tmdb_review") or c.get("youtube_review")]

