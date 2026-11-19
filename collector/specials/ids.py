"""Stable IDs. A special keeps its ID forever; merged IDs go to redirects.json."""

from __future__ import annotations

import hashlib

from .util import slugify


def candidate_id(source_key: str) -> str:
    return "cand_" + hashlib.sha1(source_key.encode("utf-8")).hexdigest()[:8]


def special_id(performers: list[str], title: str, release_date: str | None,
               taken: set[str] | dict) -> str:
    who = performers[0] if performers else "unknown"
    year = release_date[:4] if release_date else "tba"
    base = f"{who}--{slugify(title)}--{year}"
    sid, n = base, 2
    while sid in taken:
        sid = f"{base}-{n}"
        n += 1
    return sid


def add_redirect(redirects: dict[str, str], old: str, new: str) -> None:
    """Point old at new, and re-point anything that pointed at old."""
    if old == new:
        return
    for k, v in list(redirects.items()):
        if v == old:
            redirects[k] = new
    redirects[old] = new
    redirects.pop(new, None)
