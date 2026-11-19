"""`python -m specials check`: confirm each API key works, with a plain-English fix when it doesn't.

Uses almost no quota (YouTube: 2 units of the 10,000 daily). Never prints key values.
"""

from __future__ import annotations

import json

from .http import HttpError
from .sources import redact
from .sources.youtube_api import API as YT_API, key_header

TMDB = "https://api.themoviedb.org/3"
# A long-lived public video and channel used only to prove the key works.
PROBE_VIDEO = "jNQXAC9IVRw"          # "Me at the zoo", the first YouTube video
PROBE_HANDLE = "YouTube"

YT_REASONS = {
    "API_KEY_INVALID": "The key is wrong. Copy it again from Google Cloud Console → APIs & Services → Credentials, "
                       "and paste it into the YOUTUBE_API_KEY secret with no spaces or quotes.",
    "keyInvalid": "The key is wrong. Copy it again from Google Cloud Console → APIs & Services → Credentials.",
    "SERVICE_DISABLED": "The key is real, but YouTube Data API v3 isn't turned on for its project. In Google Cloud "
                        "Console, pick the same project → APIs & Services → Library → YouTube Data API v3 → Enable. "
                        "It can take a few minutes to start working.",
    "accessNotConfigured": "YouTube Data API v3 isn't enabled for this key's project. Enable it under "
                           "APIs & Services → Library.",
    "API_KEY_SERVICE_BLOCKED": "The key has API restrictions that don't include YouTube Data API v3. Edit the key under "
                               "Credentials → API restrictions and add it (or choose Don't restrict key).",
    "API_KEY_HTTP_REFERRER_BLOCKED": "The key is restricted to websites (HTTP referrers). GitHub Actions isn't a "
                                     "website. Set Application restrictions to None.",
    "API_KEY_IP_ADDRESS_BLOCKED": "The key is restricted to IP addresses. GitHub Actions uses changing IPs. Set "
                                  "Application restrictions to None.",
    "API_KEY_ANDROID_APP_BLOCKED": "The key is restricted to Android apps. Set Application restrictions to None.",
    "API_KEY_IOS_APP_BLOCKED": "The key is restricted to iOS apps. Set Application restrictions to None.",
    "quotaExceeded": "The key works, but today's quota is used up. It resets at midnight Pacific time.",
    "dailyLimitExceeded": "The key works, but today's quota is used up. It resets at midnight Pacific time.",
}


def _google_reason(body: str) -> str | None:
    try:
        err = json.loads(body).get("error") or {}
    except (ValueError, AttributeError):
        return None
    for d in err.get("details") or []:
        if d.get("reason"):
            return d["reason"]
    for e in err.get("errors") or []:
        if e.get("reason"):
            return e["reason"]
    return err.get("status")


def check_youtube(http, env: dict) -> tuple[str, str]:
    k = env.get("YOUTUBE_API_KEY")
    if not k:
        return "missing", "YOUTUBE_API_KEY isn't set. Add it under Settings → Secrets and variables → Actions."
    try:
        res = http.get_json(f"{YT_API}/videos", params={"part": "contentDetails", "id": PROBE_VIDEO},
                            headers=key_header(k))
        if not res.get("items"):
            return "fail", "The API answered but returned no video. Try again later."
        ch = http.get_json(f"{YT_API}/channels", params={"part": "id", "forHandle": PROBE_HANDLE},
                           headers=key_header(k))
        if not ch.get("items"):
            return "warn", "Video lookups work, but the channel lookup returned nothing."
        return "ok", "YouTube Data API v3 accepts the key (video and channel lookups both worked)."
    except HttpError as e:
        reason = _google_reason(e.body)
        return "fail", YT_REASONS.get(reason or "", f"HTTP {e.status} ({reason or 'no reason given'}).")
    except Exception as e:
        return "fail", f"Couldn't reach YouTube: {redact(str(e), env)[:200]}"


def check_tmdb(http, env: dict) -> tuple[str, str]:
    t = env.get("TMDB_READ_TOKEN")
    if not t:
        return "missing", "TMDB_READ_TOKEN isn't set."
    try:
        res = http.get_json(f"{TMDB}/authentication", headers={"Authorization": f"Bearer {t}"})
        if res.get("success"):
            return "ok", "TMDB accepts the token."
        return "fail", "TMDB didn't confirm the token."
    except HttpError as e:
        if e.status == 401:
            hint = (" It looks like the short 'API Key'. Use the long 'API Read Access Token' instead."
                    if len(t) < 60 else "")
            return "fail", "TMDB rejected the token." + hint + \
                " Find it at themoviedb.org → Settings → API → API Read Access Token."
        return "fail", f"HTTP {e.status} from TMDB."
    except Exception as e:
        return "fail", f"Couldn't reach TMDB: {redact(str(e), env)[:200]}"


def check_feeds(http, env: dict) -> tuple[str, str]:
    try:
        http.get_text("https://www.youtube.com/feeds/videos.xml", params={"channel_id": "UCBR8-60-B28hp2BmDPdntcQ"})
        return "ok", "YouTube channel feeds are reachable (no key needed)."
    except Exception as e:
        return "fail", f"Couldn't read a YouTube feed: {redact(str(e), env)[:200]}"


def run(http, env: dict) -> list[tuple[str, str, str]]:
    results = [("TMDB", *check_tmdb(http, env)),
               ("YouTube Data API", *check_youtube(http, env)),
               ("YouTube feeds", *check_feeds(http, env))]
    optional = {"WATCHMODE_API_KEY": "Watchmode (optional, v1.1)", "ANTHROPIC_API_KEY": "Anthropic (v1.1)"}
    for var, label in optional.items():
        results.append((label, "set" if env.get(var) else "not set", "Not used yet."))
    return results
