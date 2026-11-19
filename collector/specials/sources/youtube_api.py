"""YouTube Data API helpers shared by the feed and search collectors.

Quota (10,000 units/day by default): videos.list and channels.list cost 1 unit,
search.list costs 100. Only video IDs, titles, lengths and publish dates are stored.
"""

from __future__ import annotations

from ..titles import split_title
from ..util import contains_phrase, norm, parse_iso_duration_minutes
from . import Context, make_candidate

API = "https://www.googleapis.com/youtube/v3"


def key(ctx: Context) -> str | None:
    return ctx.env.get("YOUTUBE_API_KEY") or None


def key_header(k: str) -> dict:
    """Send the key as a header, never in the URL, so it can't end up in logs or meta.json."""
    return {"X-goog-api-key": k}


def video_details(ctx: Context, video_ids: list[str]) -> dict[str, dict]:
    """id -> {runtime_min, language, title, channel_id, published}. Empty without a key."""
    k = key(ctx)
    out: dict[str, dict] = {}
    if not k:
        return out
    ids = list(dict.fromkeys(video_ids))
    for i in range(0, len(ids), 50):
        res = ctx.http.get_json(f"{API}/videos", params={
            "part": "contentDetails,snippet", "id": ",".join(ids[i:i + 50])}, headers=key_header(k))
        for v in res.get("items", []):
            sn = v.get("snippet") or {}
            out[v["id"]] = {
                "runtime_min": parse_iso_duration_minutes((v.get("contentDetails") or {}).get("duration")),
                "language": (sn.get("defaultAudioLanguage") or sn.get("defaultLanguage") or "")[:2] or None,
                "title": sn.get("title"),
                "channel_id": sn.get("channelId"),
                "channel_title": sn.get("channelTitle"),
                "published": (sn.get("publishedAt") or "")[:10] or None,
                "live": sn.get("liveBroadcastContent") not in (None, "none"),
            }
    return out


def find_channel(ctx: Context, name: str, handle: str | None = None) -> tuple[str | None, str | None]:
    """(channel id, review note). Handle lookup is cheap; name search costs 100 units."""
    k = key(ctx)
    if not k:
        return None, None
    if handle:
        res = ctx.http.get_json(f"{API}/channels", params={
            "part": "snippet", "forHandle": handle.lstrip("@")}, headers=key_header(k))
        items = res.get("items") or []
        if items:
            return items[0]["id"], None
    res = ctx.http.get_json(f"{API}/search", params={
        "part": "snippet", "type": "channel", "q": name, "maxResults": 5}, headers=key_header(k))
    items = res.get("items") or []
    want = norm(name)
    exact = [it for it in items if norm(it["snippet"].get("channelTitle") or it["snippet"].get("title", ""))
             in (want, f"{want} comedy", f"{want} comedian", f"{want} official", f"the {want}")]
    if exact:
        return exact[0]["snippet"]["channelId"], None
    if items:
        sn = items[0]["snippet"]
        return None, f"youtube: no exact channel; closest is {sn.get('channelTitle')} ({sn.get('channelId')})"
    return None, "youtube: no channel found"


def video_candidate(ctx: Context, source: str, video_id: str, title: str, published: str | None,
                    channel_id: str | None, channel_title: str | None, details: dict | None) -> dict:
    details = details or {}
    trusted = ctx.trusted_channels.get(channel_id or "") if channel_id else None
    hint_names = [trusted["comedian_name"]] if trusted and trusted.get("comedian_name") else None
    noise = [d.get("name") for d in ctx.trusted_channels.values() if d.get("kind") == "distributor"]
    if channel_title:
        noise.append(channel_title)
    performers, clean_title, known = split_title(title, ctx.index, hint_names=hint_names,
                                                 extra_noise=[n for n in noise if n])
    scope_yt = ctx.config.scope.get("youtube") or {}
    evidence = []
    if any(contains_phrase(title, h) for h in scope_yt.get("title_hints_positive", [])):
        evidence.append("title_hint")
    if any(contains_phrase(title, h) for h in scope_yt.get("title_hints_negative", [])):
        evidence.append("negative_title_hint")
    if not known:
        evidence.append("performer_unverified")
    if details.get("live"):
        evidence.append("live_or_upcoming_stream")
    url = f"https://www.youtube.com/watch?v={video_id}"
    date = details.get("published") or published
    return make_candidate(
        source, f"youtube:{video_id}",
        title=clean_title,
        raw_title=title,
        performer_names=performers,
        release_date=date,
        runtime_min=details.get("runtime_min"),
        language=details.get("language"),
        platforms=[{"platform": "youtube", "kind": "free", "url": url, "date": date}],
        ids={"youtube": video_id},
        url=url,
        channel={"id": channel_id, "title": channel_title},
        evidence=evidence,
        trusted=bool(trusted),
        showcase=any(contains_phrase(title, h) for h in ctx.config.scope.get("showcase_title_hints", [])),
    )
