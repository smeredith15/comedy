"""`python -m specials gaps`: find systematic holes instead of adding specials one by one.

Two parts:
  * coverage report: per-source and per-year counts, comedians the collectors can't
    see yet (no TMDB ID), comedians with no specials, and which rules drop the most.
  * explain: for "Comedian: Title" (or just "Comedian"), say where the special is,
    or why it isn't in the database, and what would fix it.
"""

from __future__ import annotations

import collections
import re
import statistics

from .comedians import NameIndex
from .match import title_similarity
from .store import State
from .titles import match_key
from .util import norm

TMDB = "https://api.themoviedb.org/3"


def _table(rows: list[list], header: list[str]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


def coverage(state: State) -> str:
    specials = [s for s in state.specials.values() if not s.get("hidden")]
    tracked = [c for c in state.comedians if c.get("tracked")]
    lines = ["## Coverage", ""]

    src = collections.Counter()
    for s in specials:
        ids = s.get("ids") or {}
        for k in ("tmdb", "wikipedia", "youtube"):
            if ids.get(k):
                src[k] += 1
        if not ids.get("tmdb"):
            src["not on TMDB"] += 1
    lines += [f"{len(specials):,} specials. Found via TMDB {src['tmdb']:,} · Wikipedia {src['wikipedia']:,} · "
              f"YouTube {src['youtube']:,}. Not matched to TMDB: {src['not on TMDB']:,}.", ""]

    by_year = collections.Counter((s.get("release_date") or "")[:4] for s in specials)
    years = [y for y in sorted(by_year) if y.isdigit() and int(y) >= 2010]
    if years:
        recent = [by_year[y] for y in years[-8:]]
        med = statistics.median(recent) if recent else 0
        rows = [[y, by_year[y], "⚠️ low" if med and by_year[y] < med * 0.5 else ""] for y in years]
        lines += ["### Specials per year (2010 on)", "A year far below its neighbors usually means a source "
                  "missed it, not that fewer specials came out.", ""] + _table(rows, ["Year", "Specials", ""]) + [""]

    have = collections.Counter(p for s in specials for p in s.get("performers") or [])
    no_tmdb = [c for c in tracked if not c.get("tmdb_id")]
    zero = [c for c in tracked if c.get("tmdb_id") and not have[c["slug"]]]
    lines += ["### Comedians", f"{len(tracked)} tracked · {len(tracked) - len(no_tmdb)} with a TMDB ID · "
              f"{sum(1 for c in tracked if c.get('youtube_channel_id'))} with a YouTube channel.", ""]
    if no_tmdb:
        lines += [f"**No TMDB ID yet ({len(no_tmdb)}).** Their TMDB credits aren't checked, so any special "
                  "TMDB didn't tag as stand-up is missed. The nightly run looks these up; ones listed with a "
                  "note need you to pick the right person in `data/comedians.yaml`.", ""]
        lines += [f"- {c['name']}" + (f": {c.get('tmdb_review')}" if c.get("tmdb_review") else "")
                  for c in no_tmdb[:60]]
        if len(no_tmdb) > 60:
            lines.append(f"- …and {len(no_tmdb) - 60} more")
        lines.append("")
    if zero:
        lines += [f"**Have a TMDB ID but no specials ({len(zero)}).** Either they have none, or their specials "
                  "are somewhere the collectors don't look (their own site, Patreon, a TV series episode). "
                  "Try `gaps \"Name\"` on a few.", ""]
        lines += ["- " + ", ".join(c["name"] for c in zero[:80]), ""]

    reasons = collections.Counter()
    for r in state.rejected.values():
        for why in r.get("reasons") or []:
            reasons[(r.get("source"), re.sub(r"\d+", "N", why))] += 1
    if reasons:
        lines += ["### What the rules dropped (kept for 400 days)", "A big number on one line can mean a rule "
                  "is too strict.", ""]
        lines += _table([[s, w, n] for (s, w), n in reasons.most_common(12)], ["Source", "Reason", "Count"]) + [""]
    return "\n".join(lines)


# --- explain -----------------------------------------------------------------------

def parse_query(q: str) -> tuple[str, str | None]:
    q = q.strip().strip('"')
    for sep in (" — ", " – ", " - ", ": ", " | "):
        if sep in q:
            a, b = q.split(sep, 1)
            return a.strip(), b.strip() or None
    return q, None


def _find_comedian(state: State, name: str) -> dict | None:
    idx = NameIndex(state.comedians)
    slug = idx.lookup(name)
    if slug:
        return state.comedian(slug)
    n = norm(name)
    return next((c for c in state.comedians if norm(c.get("name", "")) == n), None)


def explain(state: State, query: str, http=None, env: dict | None = None) -> str:
    env = env or {}
    who, title = parse_query(query)
    c = _find_comedian(state, who)
    slug = c["slug"] if c else None
    lines = [f"### {who}" + (f": {title}" if title else "")]

    if c:
        bits = ["tracked" if c.get("tracked") else "not tracked (found by a collector)",
                f"TMDB person {c['tmdb_id']}" if c.get("tmdb_id") else "**no TMDB ID**",
                "YouTube channel set" if c.get("youtube_channel_id") else "no YouTube channel"]
        lines.append("Comedian: " + ", ".join(bits) + ".")
        if c.get("tmdb_review"):
            lines.append(f"TMDB lookup note: {c['tmdb_review']}")
    else:
        lines.append(f"**{who} isn't in `data/comedians.yaml`**, so their TMDB credits and YouTube channel "
                     "aren't checked. Add them to the seed file and re-run `comedians import`.")

    def matches(name_list, t) -> float:
        if not title:
            return 1.0
        return title_similarity(match_key(title, [who]), match_key(t or "", name_list))

    found = False
    for s in state.specials.values():
        if slug and slug not in s.get("performers", []):
            continue
        if not slug and norm(who) not in norm(" ".join(s.get("performers", []))):
            continue
        if matches([who], s.get("title")) >= 0.6:
            found = True
            hid = " **(hidden: you rejected it)**" if s.get("hidden") else ""
            lines.append(f"- ✅ In the database: `{s['id']}` “{s['title']}” ({s.get('release_date') or 'no date'}){hid}")
    for cand in state.candidates.values():
        if norm(who) in norm(" ".join(cand.get("performer_names") or [])) and matches([who], cand.get("title")) >= 0.6:
            found = True
            lines.append(f"- 🕓 Waiting in the review queue: `{cand['id']}` “{cand.get('title')}”: "
                         + "; ".join(cand.get("reasons") or []))
    for r in state.rejected.values():
        if norm(who) in norm(" ".join(r.get("performer_names") or [])) and matches([who], r.get("title")) >= 0.6:
            found = True
            lines.append(f"- ❌ Collected from {r.get('source')} but dropped by a rule: “{r.get('title')}”: "
                         + "; ".join(r.get("reasons") or []) + (f" ([link]({r['url']}))" if r.get("url") else ""))

    if env.get("TMDB_READ_TOKEN") and http is not None:
        lines += _tmdb_check(state, http, env, who, title, c)
    elif not found:
        lines.append("- Not seen by any collector. Run this in GitHub Actions (gaps workflow) to also check TMDB.")
    return "\n".join(lines)


def _tmdb_check(state: State, http, env, who, title, c) -> list[str]:
    h = {"Authorization": f"Bearer {env['TMDB_READ_TOKEN']}"}
    lines: list[str] = []
    hits: list[dict] = []
    try:
        if title:
            for q in (f"{who} {title}", title):
                res = http.get_json(f"{TMDB}/search/movie", params={"query": q}, headers=h)
                hits = [m for m in res.get("results", [])[:8]
                        if title_similarity(match_key(title, [who]), match_key(m.get("title", ""), [who])) >= 0.6]
                if hits:
                    break
        else:
            pid = (c or {}).get("tmdb_id")
            if not pid:
                return ["- TMDB: can't list credits without a TMDB person ID."]
            credits = http.get_json(f"{TMDB}/person/{pid}/movie_credits", headers=h)
            hits = [m for m in credits.get("cast", []) if re.match(r"^\s*(self|him|her|them)", m.get("character") or "", re.I)]
    except Exception as e:
        return [f"- TMDB check failed: {str(e)[:150]}"]
    if not hits:
        return ["- TMDB: no matching movie. It may be a TV episode, or only on YouTube / the comedian's site."]
    known = {(s.get("ids") or {}).get("tmdb") for s in state.specials.values()}
    known |= {a.split(":", 1)[1] for s in state.specials.values() for a in s.get("alt_ids") or [] if a.startswith("tmdb:")}
    for m in hits[:6]:
        try:
            d = http.get_json(f"{TMDB}/movie/{m['id']}", params={"append_to_response": "keywords,credits"}, headers=h)
        except Exception:
            continue
        kws = [k["name"] for k in (d.get("keywords") or {}).get("keywords", [])]
        tagged = any("stand-up" in k or "stand up" in k for k in kws)
        cast = [x["name"] for x in (d.get("credits") or {}).get("cast", [])[:3]]
        status = "✅ already in the database" if str(m["id"]) in known else "❌ not in the database"
        why = []
        if str(m["id"]) not in known:
            if not tagged and not (c and c.get("tmdb_id")):
                why.append("not tagged stand-up on TMDB, and the comedian has no TMDB ID, so their credits aren't checked")
            elif not tagged:
                why.append("not tagged stand-up; it's only picked up from the comedian's credits if they're billed as Self")
            if d.get("original_language") not in (None, "en"):
                why.append(f"language is {d.get('original_language')}")
            rt = d.get("runtime") or 0
            if rt and rt < 25:
                why.append(f"runtime {rt} min is under the cutoff")
            gen = {g.get("name") for g in d.get("genres") or []}
            if "Documentary" in gen:
                why.append("filed as a documentary")
        lines.append(f"- TMDB [{d.get('title')}](https://www.themoviedb.org/movie/{m['id']}) "
                     f"({d.get('release_date') or '?'}, {d.get('runtime') or '?'} min, cast: {', '.join(cast) or '?'}): "
                     f"{status}" + (f". Likely why: {'; '.join(why)}." if why else ""))
    return lines
