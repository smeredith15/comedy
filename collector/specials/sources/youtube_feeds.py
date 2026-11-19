"""YouTube channel RSS: new uploads from tracked comedians and distributors. No key, no quota."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from . import Context
from .youtube_api import video_candidate, video_details

FEED = "https://www.youtube.com/feeds/videos.xml"
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
      "media": "http://search.yahoo.com/mrss/"}


def parse_feed(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    out = []
    for e in root.findall("a:entry", NS):
        vid = e.findtext("yt:videoId", default="", namespaces=NS)
        if not vid:
            continue
        out.append({
            "video_id": vid,
            "title": e.findtext("a:title", default="", namespaces=NS),
            "published": (e.findtext("a:published", default="", namespaces=NS) or "")[:10] or None,
            "channel_id": e.findtext("yt:channelId", default="", namespaces=NS) or None,
            "channel_title": e.findtext("a:author/a:name", default="", namespaces=NS) or None,
        })
    return out


def collect(ctx: Context) -> list[dict]:
    entries = []
    for channel_id in ctx.trusted_channels:
        try:
            xml_text = ctx.http.get_text(FEED, params={"channel_id": channel_id})
            entries.extend(parse_feed(xml_text))
        except Exception as e:
            ctx.warn(f"youtube_feeds: {channel_id}: {e}")
    known = set(ctx.known_ids)
    # Durations only for videos we haven't already attached to a special.
    new_ids = [e["video_id"] for e in entries if f"youtube:{e['video_id']}" not in known]
    details = video_details(ctx, new_ids) if new_ids else {}
    return [video_candidate(ctx, "youtube_feed", e["video_id"], e["title"], e["published"],
                            e["channel_id"], e["channel_title"], details.get(e["video_id"]))
            for e in entries]
