"""A few YouTube searches a day for specials from comedians nobody is tracking yet."""

from __future__ import annotations

import datetime as dt

from . import Context, SourceSkipped
from .youtube_api import API, key, video_candidate, video_details


def collect(ctx: Context) -> list[dict]:
    k = key(ctx)
    if not k:
        raise SourceSkipped("YOUTUBE_API_KEY not set")
    if ctx.since_year:
        raise SourceSkipped("not used for backfill (search quota is small)")
    cfg = ctx.config.collector("youtube_search")
    queries = list(cfg.get("queries") or [])[: int(cfg.get("max_searches_per_day", 3))]
    after = (ctx.today - dt.timedelta(days=3)).isoformat() + "T00:00:00Z"
    hits = []
    for q in queries:
        try:
            res = ctx.http.get_json(f"{API}/search", params={
                "part": "snippet", "type": "video", "q": q, "order": "date",
                "videoDuration": "long", "publishedAfter": after, "maxResults": 25,
                "relevanceLanguage": ctx.config.scope.get("language", "en"),
                "regionCode": ctx.config.scope.get("region", "US"), "key": k})
        except Exception as e:
            ctx.warn(f"youtube_search: {q!r}: {e}")
            continue
        for it in res.get("items", []):
            vid = (it.get("id") or {}).get("videoId")
            if vid:
                sn = it.get("snippet") or {}
                hits.append((vid, sn.get("title", ""), (sn.get("publishedAt") or "")[:10] or None,
                             sn.get("channelId"), sn.get("channelTitle")))
    seen, uniq = set(), []
    for h in hits:
        if h[0] not in seen:
            seen.add(h[0])
            uniq.append(h)
    details = video_details(ctx, [h[0] for h in uniq])
    return [video_candidate(ctx, "youtube_search", vid, (details.get(vid) or {}).get("title") or title,
                            pub, ch, cht, details.get(vid))
            for vid, title, pub, ch, cht in uniq]
