"""Comedian list: import from the seed file, name lookup, and TMDB/YouTube resolution."""

from __future__ import annotations

import re
from pathlib import Path

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .store import State
from .util import iso, norm, parse_iso_date, slugify

SUFFIX_RE = re.compile(r"\s*\((comedy|comedian|comic|stand[- ]?up|humor|humour)\)\s*$", re.I)
GROUP_RE = re.compile(r"(\s&\s|\band the\b|\bband\b|\borchestra\b|\btrio\b|\bduo\b|\bquartet\b)", re.I)


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

def resolve(state: State, ctx, *, limit: int, retry_after_days: int = 30) -> dict:
    """Find TMDB person IDs and YouTube channel IDs for tracked comedians."""
    from .sources import tmdb, youtube_api

    stats = {"tmdb": 0, "youtube": 0, "needs_review": 0, "attempted": 0}
    today = ctx.today
    todo = []
    for c in state.comedians:
        if not c.get("tracked"):
            continue
        last = parse_iso_date(c.get("resolve_attempted"))
        if last and (today - last).days < retry_after_days:
            continue
        if c.get("tmdb_id") and c.get("youtube_channel_id"):
            continue
        todo.append(c)
    for c in todo[:limit]:
        stats["attempted"] += 1
        notes: list[str] = []
        if not c.get("tmdb_id") and ctx.env.get("TMDB_READ_TOKEN"):
            pid, note = tmdb.find_person(ctx, c["name"])
            if pid:
                c["tmdb_id"] = pid
                stats["tmdb"] += 1
            if note:
                notes.append(note)
        if not c.get("youtube_channel_id") and ctx.env.get("YOUTUBE_API_KEY"):
            cid, note = youtube_api.find_channel(ctx, c["name"], c.get("youtube_handle"))
            if cid:
                c["youtube_channel_id"] = cid
                stats["youtube"] += 1
            if note:
                notes.append(note)
        c["resolve_attempted"] = iso(today)
        if notes:
            c["needs_review"] = "; ".join(notes)
            stats["needs_review"] += 1
        elif "needs_review" in c:
            del c["needs_review"]
    return stats


def flagged(state: State) -> list[dict]:
    return [c for c in state.comedians
            if (c.get("flags") and not c.get("checked")) or c.get("needs_review")]

