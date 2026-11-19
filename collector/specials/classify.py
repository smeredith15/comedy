"""Scope rules: is this candidate a special? accept / review / reject, with reasons."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Decision:
    action: str                      # accept | review | reject
    reasons: list[str] = field(default_factory=list)


def runtime_format(runtime: int | None, scope: dict) -> str | None:
    if not runtime:
        return None
    return "half_hour" if runtime < int(scope.get("half_hour_max_minutes", 40)) else "hour"


def classify(c: dict, scope: dict) -> Decision:
    review: list[str] = []
    lang = scope.get("language")
    if c.get("language") and lang and c["language"] != lang:
        return Decision("reject", [f"language {c['language']}"])
    if c.get("showcase") and not scope.get("include_showcases", False):
        return Decision("reject", ["multi-comic showcase"])
    if "audio" in (c.get("evidence") or []) and not scope.get("include_audio_albums", False):
        return Decision("reject", ["audio-only release"])

    rt = c.get("runtime_min")
    min_rt = int(scope.get("min_runtime_minutes", 25))
    margin = int(scope.get("cutoff_margin_minutes", 3))
    if rt:
        if rt < min_rt - margin:
            return Decision("reject", [f"runtime {rt} min"])
        if rt < min_rt + margin:
            review.append(f"runtime {rt} min is close to the {min_rt}-minute cutoff")
        fmt = runtime_format(rt, scope)
        if fmt and fmt not in (scope.get("formats") or ["hour", "half_hour"]):
            return Decision("reject", [f"format {fmt} not in scope"])

    src = c.get("source")
    ev = set(c.get("evidence") or [])
    if src in ("youtube_feed", "youtube_search"):
        yt = scope.get("youtube") or {}
        if "negative_title_hint" in ev:
            return Decision("reject", ["title looks like a podcast/clip/trailer"])
        if "live_or_upcoming_stream" in ev:
            review.append("live or scheduled stream")
        if not c.get("trusted") and yt.get("trusted_channels_only", True):
            review.append("YouTube video from an untrusted channel")
        if "title_hint" not in ev:
            review.append("title doesn't say it's a special")
        if not rt:
            review.append("runtime unknown (no YouTube API key?)")
        if "performer_unverified" in ev:
            review.append("performer name not recognized")
    elif src == "tmdb":
        if "keyword" not in ev:
            review.append("TMDB entry isn't tagged stand-up comedy")
    elif src == "report":
        review.append("reported missing special")
    elif src == "news":
        review.append("found in the news")

    if not c.get("performers") and not c.get("performer_names"):
        review.append("no performer")
    if not c.get("title"):
        review.append("no title")
    return Decision("review" if review else "accept", review)
