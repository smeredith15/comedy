"""YouTube Data API helpers shared by the feed and search collectors.

Quota (10,000 units/day by default): videos.list and channels.list cost 1 unit,
search.list costs 100. Only video IDs, titles, lengths and publish dates are stored.
"""

from __future__ import annotations

from ..titles import split_title
import re

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


HASHTAG = re.compile(r"#\w+")
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF]")
NON_LATIN = re.compile(r"[\u0400-\u04FF\u0590-\u06FF\u0900-\u0DFF\u0E00-\u0FFF\u3040-\u30FF\u4E00-\u9FFF\uAC00-\uD7AF]")


def title_signals(title: str, scope_yt: dict) -> set[str]:
    """Evidence from the title alone. Hashtags don't count as a claim that it's a special."""
    t = HASHTAG.sub(" ", title)
    ev = set()
    if any(contains_phrase(t, h) for h in scope_yt.get("title_hints_positive", [])):
        ev.add("title_hint")
    if any(contains_phrase(t, h) for h in scope_yt.get("title_hints_negative", [])):
        ev.add("negative_title_hint")
    caps = [w for w in re.findall(r"[A-Za-z']+", t) if len(w) > 3 and w.isupper()]
    if len(EMOJI.findall(title)) >= 2 or len(caps) >= 3:
        ev.add("clickbait_title")
    if NON_LATIN.search(title):
        ev.add("non_latin_title")
    if "#shorts" in title.lower():
        ev.add("short")
    return ev


def video_candidate(ctx: Context, source: str, video_id: str, title: str, published: str | None,
                    channel_id: str | None, channel_title: str | None, details: dict | None) -> dict:
    details = details or {}
    trusted = ctx.trusted_channels.get(channel_id or "") if channel_id else None
    distributors = {norm(d.get("name") or ""): d for d in ctx.trusted_channels.values() if d.get("kind") == "distributor"}
    for d in (plain_distributors(ctx)):
        distributors.setdefault(norm(d), {"name": d, "kind": "distributor"})
    if not trusted and channel_title and norm(channel_title) in distributors:
        trusted = distributors[norm(channel_title)]          # known distributor, ID not resolved yet
    hint_names = [trusted["comedian_name"]] if trusted and trusted.get("comedian_name") else None
    noise = [d.get("name") for d in distributors.values()]
    if trusted and trusted.get("kind") == "distributor" and channel_title:
        noise.append(channel_title)
    performers, clean_title, known = split_title(HASHTAG.sub(" ", title), ctx.index, hint_names=hint_names,
                                                 extra_noise=[n for n in noise if n])
    scope_yt = ctx.config.scope.get("youtube") or {}
    evidence = sorted(title_signals(title, scope_yt))
    if not known:
        evidence.append("performer_unverified")
    if details.get("live"):
        evidence.append("live_or_upcoming_stream")
    rt = details.get("runtime_min")
    if rt is not None and rt < 5:
        evidence.append("short")
    if trusted:
        evidence.append("distributor_channel" if trusted.get("kind") == "distributor" else "comedian_channel")
    elif channel_title and performers and norm(channel_title) in {norm(p) for p in performers}:
        evidence.append("self_upload")           # e.g. "Chad Daniels" posting "Chad Daniels: Nothing To Fix"
        if "performer_unverified" in evidence:
            evidence.remove("performer_unverified")   # the channel name confirms who it is
    if trusted and trusted.get("comedian_name"):
        others = [n for n in ctx.index.find_in(title) if n != trusted.get("comedian_slug")]
        if others and trusted.get("comedian_slug") not in ctx.index.find_in(title):
            evidence.append("names_another_comedian")   # an interview or podcast guest, not their special
    url = f"https://www.youtube.com/watch?v={video_id}"
    date = details.get("published") or published
    return make_candidate(
        source, f"youtube:{video_id}",
        title=clean_title,
        raw_title=title,
        performer_names=performers,
        release_date=date,
        runtime_min=rt,
        language=details.get("language"),
        platforms=[{"platform": "youtube", "kind": "free", "url": url, "date": date}],
        ids={"youtube": video_id},
        url=url,
        channel={"id": channel_id, "title": channel_title},
        evidence=sorted(set(evidence)),
        trusted=bool(trusted),
        showcase=any(contains_phrase(title, h) for h in ctx.config.scope.get("showcase_title_hints", [])),
    )


def plain_distributors(ctx: Context) -> list[str]:
    srcs = ctx.config.sources or {}
    return [str(d.get("name")) for d in (srcs.get("distributors") or []) if d.get("name")]
