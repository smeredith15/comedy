"""News / press RSS (v1.1).

Planned: read the feeds in config/sources.yaml, keep articles that mention a
special, and turn them into candidates with an AI extraction step
(ANTHROPIC_API_KEY). Every news candidate goes to the review queue.
"""

from __future__ import annotations

from . import Context, SourceSkipped


def collect(ctx: Context) -> list[dict]:
    raise SourceSkipped("news collector is planned for v1.1")
