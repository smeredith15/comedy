"""CLI: python -m specials <command>"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import comedians, export, pipeline, review
from .config import Config, Repo, dump_yaml, find_root, load_dotenv, plain
from .http import Http
from .platforms import Platforms
from .store import build_sqlite, load_state, save_state
from .util import today


def _setup() -> tuple[Repo, Config]:
    repo = Repo(find_root())
    load_dotenv(repo.root / "collector" / ".env")
    load_dotenv(Path.cwd() / ".env")
    return repo, Config.load(repo)


def _http() -> Http:
    gh = os.environ.get("GITHUB_REPOSITORY")
    ua = "specials-tracker/0.1 (personal non-commercial project" + (
        f"; https://github.com/{gh})" if gh else ")")
    return Http(user_agent=ua)


def _sources(arg: str | None) -> list[str] | None:
    if not arg:
        return None
    if arg == "none":
        return []
    names = [s.strip() for s in arg.split(",") if s.strip()]
    bad = [n for n in names if n not in pipeline.SOURCES]
    if bad:
        sys.exit(f"unknown source(s): {', '.join(bad)}. Choose from {', '.join(pipeline.SOURCES)}")
    return names


def _print_report(report: pipeline.RunReport, state) -> None:
    for name, info in report.sources.items():
        print(f"  {name:15} {json.dumps(info, default=str)[:200]}")
    print(f"  created {len(report.created)}, merged {report.merged}, "
          f"rejected by rules {report.rejected_by_rules}, pending review {report.pending}")
    for w in report.warnings[:20]:
        print(f"  warning: {w}")


def cmd_comedians_import(args) -> None:
    repo, _ = _setup()
    state = load_state(repo)
    stats = comedians.import_seed(state, Path(args.file))
    save_state(state)
    print(f"comedians: added {stats['added']}, already present {stats['duplicates']}, "
          f"flagged for a one-time check {stats['flagged']}")


def cmd_comedians_resolve(args) -> None:
    repo, config = _setup()
    state = load_state(repo)
    ctx = pipeline.make_context(state, config, _http(), today())
    if not (ctx.env.get("TMDB_READ_TOKEN") or ctx.env.get("YOUTUBE_API_KEY")):
        sys.exit("Set TMDB_READ_TOKEN and/or YOUTUBE_API_KEY (collector/.env) first.")
    rcfg = plain(config.sources).get("resolve") or {}
    stats = comedians.resolve(state, ctx, limit=args.limit,
                              retry_after_days=0 if args.retry else int(rcfg.get("retry_after_days", 30)))
    save_state(state)
    print(f"resolve: {stats}")


def cmd_sources_resolve(args) -> None:
    from .sources.youtube_api import find_channel
    repo, config = _setup()
    state = load_state(repo)
    ctx = pipeline.make_context(state, config, _http(), today())
    if not ctx.env.get("YOUTUBE_API_KEY"):
        sys.exit("Set YOUTUBE_API_KEY first.")
    changed = 0
    for d in config.sources.get("distributors") or []:
        if d.get("channel_id"):
            continue
        cid, note = find_channel(ctx, d["name"], d.get("handle"))
        print(f"  {d['name']}: {cid or '-'} {note or ''}")
        if cid:
            d["channel_id"] = cid
            changed += 1
    if changed:
        dump_yaml(repo.config / "sources.yaml", config.sources)
    print(f"distributors resolved: {changed}")


def _run(args, since_year=None) -> None:
    repo, config = _setup()
    state = load_state(repo)
    http = _http()
    token, slug = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    extra = []
    decided = 0
    if getattr(args, "github_issue", False) and token and slug:
        for label, step in (("review-queue boxes", review.read_issue_decisions),
                            ("not-a-special issues", review.apply_removal_requests)):
            try:
                n = step(http, token, slug, state)
                decided += n
                if n:
                    print(f"  applied {n} decision(s) from {label}")
            except Exception as e:
                print(f"  warning: couldn't read {label}: {e}")
        try:
            extra = review.fetch_reports(http, token, slug, Platforms(config.platforms))
        except Exception as e:
            print(f"  warning: couldn't read missing-special issues: {e}")
    rcfg = plain(config.sources).get("resolve") or {}
    report = pipeline.run(state, config, http, today=today(), since_year=since_year,
                          sources=_sources(args.sources), extra=extra,
                          resolve_limit=0 if args.sources else int(rcfg.get("per_night_limit", 25)))
    save_state(state, overrides=bool(decided))
    export.write(state, config)
    build_sqlite(state)
    print(f"{'backfill' if since_year else 'nightly'}: {state.meta['counts']}")
    _print_report(report, state)
    if getattr(args, "github_issue", False):
        if token and slug:
            url = review.update_issue(http, token, slug, state)
            print(f"  review issue: {url}")
            closed = review.close_resolved_reports(http, token, slug, state)
            if closed:
                print(f"  closed {closed} reviewed missing-special issue(s)")
        else:
            print("  (no GITHUB_TOKEN / GITHUB_REPOSITORY: review issue not updated)")


def cmd_nightly(args) -> None:
    _run(args)


def cmd_backfill(args) -> None:
    _run(args, since_year=args.since)


def cmd_review(args) -> None:
    repo, _ = _setup()
    review.interactive(load_state(repo))


def cmd_queue(args) -> None:
    repo, _ = _setup()
    print(review.queue_markdown(load_state(repo), os.environ.get("GITHUB_REPOSITORY")))


def cmd_export(args) -> None:
    repo, config = _setup()
    state = load_state(repo)
    path = export.write(state, config, Path(args.out) if args.out else None)
    print(f"wrote {path}")


def cmd_db(args) -> None:
    repo, _ = _setup()
    print(f"wrote {build_sqlite(load_state(repo))}")


def cmd_gaps(args) -> None:
    from . import gaps
    repo, _ = _setup()
    state = load_state(repo)
    queries = list(args.query or [])
    if args.file:
        queries += [l.strip() for l in Path(args.file).read_text().splitlines() if l.strip() and not l.startswith("#")]
    out = [] if args.no_coverage else [gaps.coverage(state)]
    if queries:
        out.append("## Specials you asked about")
        http = _http()
        out += [gaps.explain(state, q, http, dict(os.environ)) for q in queries]
    print("\n\n".join(out))


def cmd_check(args) -> None:
    from . import check
    _setup()
    results = check.run(_http(), dict(os.environ))
    icons = {"ok": "✅", "warn": "⚠️", "fail": "❌", "missing": "❌", "set": "•", "not set": "•"}
    for name, status, msg in results:
        print(f"{icons.get(status, '•')} {name}: {status}. {msg}")
    if any(status in ("fail", "missing") for name, status, _ in results if not name.startswith(("Watchmode", "Anthropic"))):
        sys.exit(1)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="python -m specials", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("comedians", help="manage the comedian list")
    csub = c.add_subparsers(dest="sub", required=True)
    ci = csub.add_parser("import", help="import names from a seed file")
    ci.add_argument("file")
    ci.set_defaults(func=cmd_comedians_import)
    cr = csub.add_parser("resolve", help="find TMDB person + YouTube channel IDs")
    cr.add_argument("--limit", type=int, default=50, help="comedians per run (YouTube search = 100 quota units)")
    cr.add_argument("--retry", action="store_true", help="retry ones attempted recently")
    cr.set_defaults(func=cmd_comedians_resolve)

    s = sub.add_parser("sources", help="distributor channels")
    ssub = s.add_subparsers(dest="sub", required=True)
    sr = ssub.add_parser("resolve", help="look up distributor channel IDs from their handles")
    sr.set_defaults(func=cmd_sources_resolve)

    for name, func, helptext in (("nightly", cmd_nightly, "collect → classify → match → export"),
                                 ("backfill", cmd_backfill, "one-time history load")):
        n = sub.add_parser(name, help=helptext)
        n.add_argument("--sources", help=f"comma list of {','.join(pipeline.SOURCES)}, or 'none' "
                                         "to only re-apply overrides")
        n.add_argument("--github-issue", action="store_true",
                       help="update the review-queue issue and read missing-special issues")
        if name == "backfill":
            n.add_argument("--since", type=int, required=True)
        n.set_defaults(func=func)

    sub.add_parser("review", help="review pending candidates in the terminal").set_defaults(func=cmd_review)
    sub.add_parser("queue", help="print the review queue as markdown").set_defaults(func=cmd_queue)
    e = sub.add_parser("export", help="write app/public/data/db.json")
    e.add_argument("--out")
    e.set_defaults(func=cmd_export)
    sub.add_parser("db", help="rebuild the SQLite cache").set_defaults(func=cmd_db)
    sub.add_parser("check", help="confirm the API keys work").set_defaults(func=cmd_check)
    g = sub.add_parser("gaps", help="coverage report, and why specific specials are missing")
    g.add_argument("query", nargs="*", help='"Comedian: Title" or just "Comedian"')
    g.add_argument("--file", help="one query per line")
    g.add_argument("--no-coverage", action="store_true", help="only explain the queries")
    g.set_defaults(func=cmd_gaps)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
