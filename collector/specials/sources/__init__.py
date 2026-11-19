"""Collectors. Each `collect(ctx)` returns a list of raw candidate dicts."""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, field

from ..comedians import NameIndex
from ..config import Config
from ..ids import candidate_id
from ..platforms import Platforms


SECRET_VARS = ("TMDB_READ_TOKEN", "YOUTUBE_API_KEY", "WATCHMODE_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN")


def redact(text: str, env: dict | None = None) -> str:
    """Blank out any secret values that slipped into a message before it is logged or committed."""
    env = env if env is not None else os.environ
    for var in SECRET_VARS:
        v = env.get(var)
        if v and len(v) >= 8:
            text = text.replace(v, "***")
    return text


class SourceSkipped(Exception):
    """Raised when a collector can't run (missing key, disabled for this mode)."""


@dataclass
class Context:
    http: object
    config: Config
    index: NameIndex
    today: dt.date
    env: dict = field(default_factory=lambda: dict(os.environ))
    since_year: int | None = None          # set for backfill
    known_ids: dict = field(default_factory=dict)  # "tmdb:123" -> special id
    trusted_channels: dict = field(default_factory=dict)  # channel id -> {"name", "comedian"?}
    comedians: list = field(default_factory=list)        # comedians.yaml entries
    log: list = field(default_factory=list)

    @property
    def platforms(self) -> Platforms:
        if not hasattr(self, "_platforms"):
            self._platforms = Platforms(self.config.platforms)
        return self._platforms

    def warn(self, msg: str) -> None:
        self.log.append(redact(msg, self.env))


def make_candidate(source: str, source_key: str, **fields) -> dict:
    c = {
        "id": candidate_id(source_key),
        "source": source,
        "source_key": source_key,
        "title": None,
        "raw_title": None,
        "performers": [],
        "performer_names": [],
        "release_date": None,
        "runtime_min": None,
        "language": None,
        "platforms": [],
        "ids": {},
        "url": None,
        "evidence": [],
        "showcase": False,
        "trusted": False,
    }
    c.update({k: v for k, v in fields.items() if v is not None})
    return c
