"""TMDB: stand-up specials on streaming and TV, with runtimes, IMDb IDs and where to watch.

This product uses the TMDB API but is not endorsed or certified by TMDB.
Where-to-watch data comes from JustWatch via TMDB.
"""

from __future__ import annotations

import datetime as dt

import re

from ..util import iso, norm, parse_iso_date
from . import Context, SourceSkipped, make_candidate

API = "https://api.themoviedb.org/3"
COMEDY_GENRE = 35
DOCUMENTARY_GENRE = 99
SELF_CHARACTER = re.compile(r"^\s*(self|him\s*self|her\s*self|them\s*selves|themselves|himself|herself|narrator, self)\b", re.I)
KIND = {"flatrate": "subscription", "free": "free", "ads": "ads"}


def _headers(ctx: Context) -> dict:
    token = ctx.env.get("TMDB_READ_TOKEN")
    if not token:
        raise SourceSkipped("TMDB_READ_TOKEN not set")
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _get(ctx: Context, path: str, **params):
    return ctx.http.get_json(API + path, params=params or None, headers=_headers(ctx))


def keyword_ids(ctx: Context) -> list[int]:
    out = []
    for name in ctx.config.collector("tmdb").get("discover_keywords") or ["stand-up comedy"]:
        res = _get(ctx, "/search/keyword", query=name)
        hits = [k["id"] for k in res.get("results", []) if norm(k.get("name", "")) == norm(name)]
        if hits:
            out.append(hits[0])
        else:
            ctx.warn(f"tmdb: keyword {name!r} not found")
    return out


def find_person(ctx: Context, name: str) -> tuple[int | None, str | None]:
    """(person id, review note). Only exact-name matches are taken automatically."""
    res = _get(ctx, "/search/person", query=name)
    exact = [p for p in res.get("results", []) if norm(p.get("name", "")) == norm(name)]
    if len(exact) == 1:
        return exact[0]["id"], None
    if len(exact) > 1:
        acting = [p for p in exact if p.get("known_for_department") == "Acting"]
        best = max(acting or exact, key=lambda p: p.get("popularity") or 0)
        ids = ", ".join(str(p["id"]) for p in exact)
        return best["id"], f"tmdb: {len(exact)} people named {name} ({ids}); picked {best['id']}"
    if res.get("results"):
        p = res["results"][0]
        return None, f"tmdb: no exact match; closest is {p.get('name')} ({p['id']})"
    return None, "tmdb: no person found"


def collect(ctx: Context) -> list[dict]:
    _headers(ctx)
    cfg = ctx.config.collector("tmdb")
    today = ctx.today
    if ctx.since_year:
        start = dt.date(ctx.since_year, 1, 1)
    else:
        start = today - dt.timedelta(days=int(cfg.get("lookback_days", 60)))
    end = today + dt.timedelta(days=int(cfg.get("lookahead_days", 365)))

    kw = keyword_ids(ctx)
    movie_ids: dict[int, set[str]] = {}
    if kw:
        page, pages = 1, 1
        max_pages = int(cfg.get("max_pages", 200))
        while page <= min(pages, max_pages, 500):
            res = _get(ctx, "/discover/movie", with_keywords="|".join(map(str, kw)),
                       **{"primary_release_date.gte": iso(start), "primary_release_date.lte": iso(end)},
                       sort_by="primary_release_date.desc", include_adult="false", page=page)
            pages = res.get("total_pages", 1)
            for m in res.get("results", []):
                movie_ids.setdefault(m["id"], set()).add("keyword")
            page += 1

    if cfg.get("person_credits", True):
        for slug, person in _tracked_people(ctx):
            try:
                credits = _get(ctx, f"/person/{person}/movie_credits")
            except Exception as e:  # one bad person shouldn't stop the run
                ctx.warn(f"tmdb: credits for {slug}: {e}")
                continue
            for m in credits.get("cast", []):
                d = parse_iso_date(m.get("release_date"))
                genres = m.get("genre_ids") or []
                is_self = bool(SELF_CHARACTER.match(m.get("character") or ""))
                # Specials are usually filed as Comedy, but plenty have no genre at all.
                if genres and COMEDY_GENRE not in genres and not is_self:
                    continue
                if d and not (start <= d <= end):
                    continue
                movie_ids.setdefault(m["id"], set()).update(
                    {"person_credit", f"credit_of:{slug}"} | ({"self_credit"} if is_self else set()))

    out = []
    for mid, how in sorted(movie_ids.items()):
        try:
            details = _get(ctx, f"/movie/{mid}",
                           append_to_response="credits,external_ids,watch/providers,release_dates,keywords")
        except Exception as e:
            ctx.warn(f"tmdb: movie {mid}: {e}")
            continue
        cand = to_candidate(ctx, details, kw, how)
        if cand:
            out.append(cand)
    return out


def _tracked_people(ctx: Context):
    for c in ctx.comedians:
        if c.get("tracked") and c.get("tmdb_id"):
            yield c["slug"], c["tmdb_id"]


def to_candidate(ctx: Context, m: dict, keyword_ids_: list[int], how: set[str]) -> dict | None:
    region = ctx.config.scope.get("region", "US")
    kw_ids = {k["id"] for k in (m.get("keywords") or {}).get("keywords", [])}
    evidence = sorted(how | ({"keyword"} if kw_ids & set(keyword_ids_) else set()))
    cast = sorted((m.get("credits") or {}).get("cast", []), key=lambda c: c.get("order", 99))
    cast_names = [c["name"] for c in cast]

    performers, title = _performers_and_title(ctx, m.get("title") or "", cast_names)
    known = bool(performers)
    evidence = [e for e in evidence if not e.startswith("credit_of:")]
    if "person_credit" in how and "keyword" not in evidence:
        # A tracked comic's credit that TMDB didn't tag stand-up: keep it if it's shaped like a special.
        rt = m.get("runtime") or 0
        genres = {g.get("id") for g in m.get("genres") or []}
        if not 20 <= rt <= 100 or DOCUMENTARY_GENRE in genres:
            return None
        plays_self = "self_credit" in how
        named_title = known and ":" in (m.get("title") or "")
        if not (plays_self or named_title):
            return None
        evidence.append("special_shaped_title" if named_title else "plays_self")
        # Solo: they're the top-billed (or only) cast member.
        credited = {x.split(":", 1)[1] for x in how if x.startswith("credit_of:")}
        top = cast[0]["name"] if cast else None
        if len(cast) <= 3 and (not top or any(ctx.index.lookup(top) == s for s in credited) or len(cast) == 1):
            evidence.append("solo_credit")

    release = _us_release(m, region) or m.get("release_date") or None
    platforms = []
    wp = ((m.get("watch/providers") or {}).get("results") or {}).get(region) or {}
    for key, kind in KIND.items():
        for p in wp.get(key, []) or []:
            e = ctx.platforms.entry(p.get("provider_name", ""), kind=kind)
            if not any(x["platform"] == e["platform"] for x in platforms):
                platforms.append(e)

    showcase = len(set(n for n in performers)) > 2 or _showcase_title(ctx, m.get("title", ""))
    return make_candidate(
        "tmdb", f"tmdb:{m['id']}",
        title=title or m.get("title"),
        raw_title=m.get("title"),
        performer_names=performers,
        release_date=release,
        runtime_min=m.get("runtime") or None,
        language=m.get("original_language"),
        platforms=platforms,
        ids={"tmdb": str(m["id"]), "imdb": (m.get("external_ids") or {}).get("imdb_id") or m.get("imdb_id")},
        url=f"https://www.themoviedb.org/movie/{m['id']}",
        evidence=evidence,
        showcase=showcase,
        trusted=True,
    )


def _performers_and_title(ctx: Context, raw: str, cast_names: list[str]) -> tuple[list[str], str]:
    """'Jane Doe: Example Hour' -> (['Jane Doe'], 'Example Hour'); otherwise top-billed cast."""
    cast_norm = {norm(n): n for n in cast_names}
    if ":" in raw:
        prefix, rest = (x.strip() for x in raw.split(":", 1))
        names = [n.strip() for n in re.split(r"\s+(?:&|and)\s+|,\s*", prefix) if n.strip()]
        found = []
        for n in names:
            if norm(n) in cast_norm:
                found.append(cast_norm[norm(n)])
            elif ctx.index.lookup(n):
                found.append(ctx.index.names.get(ctx.index.lookup(n), n))
        if names and len(found) == len(names) and rest:
            return found, rest
    if cast_names:
        first = cast_names[0]
        if norm(raw).startswith(norm(first) + " "):
            return [first], raw[len(first):].strip(" :-–—") or raw
        return [first], raw
    return [], raw


def _us_release(m: dict, region: str) -> str | None:
    for r in (m.get("release_dates") or {}).get("results", []):
        if r.get("iso_3166_1") == region:
            dates = sorted(d["release_date"][:10] for d in r.get("release_dates", []) if d.get("release_date"))
            if dates:
                return dates[0]
    return None


def _showcase_title(ctx: Context, title: str) -> bool:
    from ..util import contains_phrase
    return any(contains_phrase(title, h) for h in ctx.config.scope.get("showcase_title_hints", []))
