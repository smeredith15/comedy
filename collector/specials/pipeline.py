"""collect → classify → match/merge → apply overrides → (export)."""

from __future__ import annotations

import copy
import datetime as dt
import json
import time
from dataclasses import dataclass, field

from . import comedians as comedians_mod
from .classify import classify
from .comedians import NameIndex, ensure_performers
from .config import Config, plain
from .ids import add_redirect
from .match import Matcher, derive, merge_into, new_special
from .sources import Context, SourceSkipped, redact
from .store import State
from .util import iso

SOURCES = ["tmdb", "wikipedia", "youtube_feeds", "youtube_search", "news", "watchmode"]
EDITABLE = {"title", "performers", "format", "runtime_min", "release_date", "public_release_date",
            "status", "language", "platforms"}


@dataclass
class RunReport:
    sources: dict = field(default_factory=dict)
    created: list = field(default_factory=list)
    merged: int = 0
    pending: int = 0
    rejected_by_rules: int = 0
    warnings: list = field(default_factory=list)


def trusted_channels(state: State, config: Config) -> dict:
    out = {}
    for d in (plain(config.sources).get("distributors") or []):
        if d.get("channel_id"):
            out[d["channel_id"]] = {"name": d.get("name"), "kind": "distributor"}
    for c in state.comedians:
        if c.get("tracked") and c.get("youtube_channel_id"):
            out[c["youtube_channel_id"]] = {"name": c.get("name"), "kind": "comedian",
                                            "comedian_name": c.get("name"), "comedian_slug": c.get("slug")}
    return out


def resolve_distributors(state: State, config: Config, ctx: Context) -> int:
    """Fill in missing distributor channel IDs in config/sources.yaml (1 quota unit each by handle)."""
    from .config import dump_yaml
    from .sources.youtube_api import find_channel
    if not ctx.env.get("YOUTUBE_API_KEY"):
        return 0
    changed = 0
    for d in config.sources.get("distributors") or []:
        if d.get("channel_id") or not d.get("handle"):
            continue
        cid, _ = find_channel(ctx, d["name"], d.get("handle"))
        if cid:
            d["channel_id"] = cid
            changed += 1
    if changed:
        dump_yaml(state.repo.config / "sources.yaml", config.sources)
    return changed


def make_context(state: State, config: Config, http, today: dt.date, since_year: int | None = None,
                 env: dict | None = None) -> Context:
    ctx = Context(http=http, config=config, index=NameIndex(state.comedians), today=today,
                  since_year=since_year,
                  comedians=[plain(c) for c in state.comedians],
                  trusted_channels=trusted_channels(state, config))
    if env is not None:
        ctx.env = env
    for s in state.specials.values():
        for k in ("tmdb", "imdb", "youtube"):
            v = (s.get("ids") or {}).get(k)
            if v:
                ctx.known_ids[f"{k}:{v}"] = s["id"]
    return ctx


def collect(ctx: Context, names: list[str], report: RunReport) -> list[dict]:
    import importlib
    out: list[dict] = []
    for name in names:
        if not ctx.config.enabled(name):
            report.sources[name] = {"status": "disabled"}
            continue
        mod = importlib.import_module(f".sources.{name}", __package__)
        t0 = time.time()
        before = len(ctx.log)
        try:
            items = mod.collect(ctx)
            report.sources[name] = {"status": "ok", "items": len(items),
                                    "seconds": round(time.time() - t0, 1)}
            out.extend(items)
        except SourceSkipped as e:
            report.sources[name] = {"status": "skipped", "reason": str(e)}
        except Exception as e:   # a broken source shouldn't stop the others
            report.sources[name] = {"status": "error",
                                    "error": redact(f"{type(e).__name__}: {e}", ctx.env)[:300]}
        if len(ctx.log) > before:
            info = report.sources.setdefault(name, {})
            info["warnings"] = [w[:300] for w in ctx.log[before:][:20]]
            if info.get("status") == "ok" and not info.get("items"):
                info["status"] = "error"     # every request failed
    return out


def process(state: State, config: Config, collected: list[dict], today: dt.date,
            report: RunReport | None = None) -> RunReport:
    report = report or RunReport()
    scope = config.scope
    before = {sid: _content(s) for sid, s in state.specials.items()}
    index = NameIndex(state.comedians)
    matcher = Matcher(state.specials, index.names, scope)

    rejects = set(state.override_list("reject"))
    blocked = {str(x) for x in state.override_list("block_channels")}
    accepts = set(state.override_list("accept"))
    merges = {m[0]: m[1] for m in state.override_list("merge") if m and len(m) == 2}

    # Previously pending candidates get re-evaluated too; fresh copies win.
    pool: dict[str, dict] = {cid: _refresh(c, scope) for cid, c in state.candidates.items()}
    for c in collected:
        prev = pool.get(c["id"])
        c["first_seen"] = (prev or {}).get("first_seen") or iso(today)
        pool[c["id"]] = c
    pending: dict[str, dict] = {}

    for cid, c in sorted(pool.items()):
        if cid in rejects:
            continue
        c["performers"] = _performer_slugs(state, c, index)
        if (c.get("channel") or {}).get("id") in blocked:
            c["channel_blocked"] = True
        target = merges.get(cid)
        if target:
            sid = state.resolve_id(target)
            if sid in state.specials:
                merge_into(state.specials[sid], c)
                matcher.index(state.specials[sid])
                report.merged += 1
                continue
        sid, strength, sim = matcher.find(c)
        if strength == "id":
            merge_into(state.specials[sid], c)
            matcher.index(state.specials[sid])
            report.merged += 1
            continue
        if cid in accepts:
            decision_action, reasons = "accept", []
        else:
            d = classify(c, scope)
            decision_action, reasons = d.action, d.reasons
        if decision_action == "reject":
            report.rejected_by_rules += 1
            _log_rejection(state, c, reasons, today)
            continue
        if decision_action == "accept" and strength == "strong":
            merge_into(state.specials[sid], c)
            matcher.index(state.specials[sid])
            report.merged += 1
            continue
        if decision_action == "accept" and (strength is None or cid in accepts):
            ensure_performers(state, c.get("performer_names") or [], index)
            s = new_special(c, state.specials.keys() | state.redirects.keys(), today)
            state.specials[s["id"]] = s
            matcher.index(s)
            report.created.append(s["id"])
            continue
        # review
        if strength == "partial":
            reasons = reasons + [f"partial title match ({sim:.2f}) with {sid}"]
        elif strength == "strong":
            reasons = reasons + [f"looks like {sid}"]
        c["reasons"] = reasons
        c["match"] = sid
        c["updated"] = iso(today)
        pending[cid] = _candidate_record(c)

    state.candidates = pending
    _prune_rejected(state, today)
    _apply_special_overrides(state)
    for s in state.specials.values():
        derive(s, scope, today)
    _apply_edits(state, today)

    for sid, s in state.specials.items():
        if sid not in before:
            s["first_seen"] = s.get("first_seen") or iso(today)
            s["updated"] = iso(today)
        elif _content(s) != before[sid]:
            s["updated"] = iso(today)
    report.pending = len(state.candidates)
    return report


# Rejections worth keeping for `specials gaps` ("why isn't X here?"). YouTube noise
# (Shorts, clips, untitled uploads) is left out so the file stays small.
_NOISE = ("a Short or clip", "title doesn't say it's a special", "clickbait", "title isn't in English",
          "title looks like a podcast", "channel is on your ignore list")
REJECTED_KEEP_DAYS = 400


TITLE_FLAGS = {"title_hint", "negative_title_hint", "clickbait_title", "non_latin_title"}


def _refresh(c: dict, scope: dict) -> dict:
    """Re-check a waiting YouTube candidate's title with the current rules (they may have changed)."""
    if c.get("source", "").startswith("youtube") and c.get("raw_title"):
        from .sources.youtube_api import title_signals
        ev = set(c.get("evidence") or []) - TITLE_FLAGS
        ev |= title_signals(c["raw_title"], scope.get("youtube") or {})
        if c.get("runtime_min") is not None and c["runtime_min"] < 5:
            ev.add("short")
        c["evidence"] = sorted(ev)
    return c


def _log_rejection(state: State, c: dict, reasons: list[str], today: dt.date) -> None:
    if c.get("source", "").startswith("youtube") and any(r.startswith(_NOISE) for r in reasons):
        return
    state.rejected[c["id"]] = {
        "id": c["id"], "source": c.get("source"), "performer_names": c.get("performer_names") or [],
        "title": c.get("title"), "release_date": c.get("release_date"), "runtime_min": c.get("runtime_min"),
        "url": c.get("url"), "reasons": reasons, "last_seen": iso(today)}


def _prune_rejected(state: State, today: dt.date) -> None:
    cutoff = iso(today - dt.timedelta(days=REJECTED_KEEP_DAYS))
    state.rejected = {k: v for k, v in state.rejected.items() if (v.get("last_seen") or "") >= cutoff}


def _performer_slugs(state: State, c: dict, index: NameIndex) -> list[str]:
    slugs = []
    for name in c.get("performer_names") or []:
        slug = index.lookup(name)
        if not slug:
            from .util import slugify
            slug = slugify(name)
        if slug not in slugs:
            slugs.append(slug)
    return slugs or list(c.get("performers") or [])


def _candidate_record(c: dict) -> dict:
    keep = ["id", "source", "source_key", "title", "raw_title", "performers", "performer_names",
            "release_date", "runtime_min", "language", "platforms", "ids", "url", "channel",
            "evidence", "showcase", "trusted", "reasons", "match", "first_seen", "updated"]
    return {k: c.get(k) for k in keep if c.get(k) not in (None, [], {})} | {"id": c["id"]}


def _apply_special_overrides(state: State) -> None:
    for pair in state.override_list("merge"):
        if not pair or len(pair) != 2:
            continue
        src, dst = str(pair[0]), state.resolve_id(str(pair[1]))
        src = state.resolve_id(src) if not src.startswith("cand_") else src
        if src.startswith("cand_") or src == dst:
            continue
        if src in state.specials and dst in state.specials:
            a, b = state.specials.pop(src), state.specials[dst]
            merge_into(b, {**a, "url": None, "source": "merge"})
            add_redirect(state.redirects, src, dst)
    for rid in state.override_list("reject"):
        sid = state.resolve_id(str(rid))
        if sid in state.specials:
            state.specials[sid]["hidden"] = True


def _apply_edits(state: State, today: dt.date) -> None:
    edits = plain(state.overrides.get("edit") or {})
    for raw_id, fields in edits.items():
        sid = state.resolve_id(raw_id)
        s = state.specials.get(sid)
        if not s or not isinstance(fields, dict):
            continue
        for k, v in fields.items():
            if k in EDITABLE:
                s[k] = copy.deepcopy(v)


def _content(s: dict) -> str:
    return json.dumps({k: v for k, v in s.items() if k not in ("updated", "first_seen")}, sort_keys=True)


def run(state: State, config: Config, http, *, today: dt.date, since_year: int | None = None,
        sources: list[str] | None = None, env: dict | None = None, resolve_limit: int | None = None,
        extra: list[dict] | None = None) -> RunReport:
    report = RunReport()
    ctx = make_context(state, config, http, today, since_year, env)
    if resolve_limit:
        rcfg = plain(config.sources).get("resolve") or {}
        try:
            report.sources["resolve"] = comedians_mod.resolve(
                state, ctx, limit=resolve_limit, retry_after_days=int(rcfg.get("retry_after_days", 30)))
        except Exception as e:
            report.sources["resolve"] = {"status": "error", "error": redact(str(e), ctx.env)[:300]}
        try:
            n = resolve_distributors(state, config, ctx)
            if n:
                report.sources["resolve"]["distributors"] = n
        except Exception as e:
            report.sources["resolve"]["distributors_error"] = redact(str(e), ctx.env)[:200]
        ctx = make_context(state, config, http, today, since_year, env)
    collected = collect(ctx, SOURCES if sources is None else sources, report)
    if extra:
        collected.extend(extra)
        report.sources["reports"] = {"status": "ok", "items": len(extra)}
    process(state, config, collected, today, report)
    report.warnings = ctx.log
    visible = [s for s in state.specials.values() if not s.get("hidden")]
    state.meta = {
        "last_run": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "mode": "backfill" if since_year else "nightly",
        "counts": {
            "specials": len(visible),
            "released": sum(s.get("status") == "released" for s in visible),
            "upcoming": sum(s.get("status") in ("upcoming", "announced") for s in visible),
            "comedians_tracked": sum(bool(c.get("tracked")) for c in state.comedians),
            "candidates_pending": report.pending,
            "created_this_run": len(report.created),
            "merged_this_run": report.merged,
            "rejected_by_rules_this_run": report.rejected_by_rules,
        },
        "sources": report.sources,
    }
    return report
