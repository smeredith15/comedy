"""Platform name normalization."""

from __future__ import annotations

from .util import norm, slugify

FREE_KINDS = {"free", "ads"}


class Platforms:
    def __init__(self, table: dict):
        self.table = table or {}
        self._alias: dict[str, str] = {}
        for slug, info in self.table.items():
            self._alias[norm(slug)] = slug
            self._alias[norm(info.get("name", slug))] = slug
            for a in info.get("aliases") or []:
                self._alias[norm(a)] = slug

    def slug(self, name: str) -> str:
        n = norm(name)
        if n in self._alias:
            return self._alias[n]
        for suffix in ("with ads", "amazon channel", "apple tv channel", "roku premium channel",
                       "standard with ads", "basic with ads"):
            if n.endswith(" " + suffix):
                base = n[: -len(suffix) - 1]
                if base in self._alias:
                    return self._alias[base]
        return slugify(name)

    def default_kind(self, slug: str) -> str:
        return (self.table.get(slug) or {}).get("kind", "subscription")

    def entry(self, name: str, kind: str | None = None, url: str | None = None,
              date: str | None = None) -> dict:
        slug = self.slug(name)
        e = {"platform": slug, "kind": kind or self.default_kind(slug), "url": url}
        if date:
            e["date"] = date
        return e
