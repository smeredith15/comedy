"""Watchmode (optional, v1.1): a second check on streaming availability."""

from __future__ import annotations

from . import Context, SourceSkipped


def collect(ctx: Context) -> list[dict]:
    if not ctx.env.get("WATCHMODE_API_KEY"):
        raise SourceSkipped("WATCHMODE_API_KEY not set")
    raise SourceSkipped("Watchmode availability checks are planned for v1.1")
