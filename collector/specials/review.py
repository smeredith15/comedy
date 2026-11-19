"""Review queue: the nightly GitHub issue, missing-special reports, and a terminal review."""

from __future__ import annotations

import re

from ruamel.yaml.comments import CommentedSeq

from .comedians import flagged
from .ids import candidate_id
from .sources import make_candidate
from .store import State, save_overrides

GITHUB_API = "https://api.github.com"
QUEUE_LABEL = "review-queue"
REPORT_LABEL = "missing-special"
REMOVE_LABEL = "not-a-special"


# --- the queue as markdown ---------------------------------------------------

def _md(text) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ")


MAX_LISTED = 80
# Checkbox lines the nightly job reads back. Keep the leading words stable.
BOX_ACCEPT = "It's a special"
BOX_REJECT = "Not a special (never show again)"
BOX_BLOCK = "Not a special, and ignore this YouTube channel"
BOX_MERGE = "Same special as"
CAND_HEADER = re.compile(r"^#{3,4}\s+`(cand_[0-9a-f]{8})`")
CHECKED = re.compile(r"^\s*[-*]\s+\[[xX]\]\s+(.*)$")


def queue_markdown(state: State, repo_slug: str | None = None) -> str:
    cands = sorted(state.candidates.values(), key=lambda c: (c.get("release_date") or "", c["id"]), reverse=True)
    edit_link = (f"https://github.com/{repo_slug}/edit/main/data/overrides.yaml" if repo_slug
                 else "data/overrides.yaml")
    lines = [
        f"**{len(cands)} candidate(s) waiting.** Tick a box under each one. The next nightly run "
        f"records your choice in [`data/overrides.yaml`]({edit_link}) and drops it from this list. "
        "Leave it unticked to decide later.",
        "",
    ]
    for c in cands[:MAX_LISTED]:
        who = ", ".join(c.get("performer_names") or c.get("performers") or []) or "?"
        src = f"[{c.get('source')}]({c['url']})" if c.get("url") else c.get("source")
        facts = " · ".join(x for x in [c.get("release_date") or "no date",
                                       f"{c['runtime_min']} min" if c.get("runtime_min") else "",
                                       src, (c.get("channel") or {}).get("title") or ""] if x)
        lines += [f"#### `{c['id']}` {_md(who)}: {_md(c.get('title'))}",
                  f"{facts}  ",
                  f"_{_md('; '.join(c.get('reasons') or []))}_",
                  "",
                  f"- [ ] {BOX_ACCEPT}",
                  f"- [ ] {BOX_REJECT}"]
        if (c.get("channel") or {}).get("id"):
            lines.append(f"- [ ] {BOX_BLOCK}")
        if c.get("match"):
            lines.append(f"- [ ] {BOX_MERGE} `{c['match']}`")
        lines.append("")
    if len(cands) > MAX_LISTED:
        lines += [f"_…and {len(cands) - MAX_LISTED} more. They appear here as the list shrinks, "
                  "or run `python -m specials review` on a computer._", ""]
    people = flagged(state)
    if people:
        lines += ["", f"### Comedians to check ({len(people)})",
                  "Edit `data/comedians.yaml`: fix the ID if the match is wrong, then set `checked: true` "
                  "or delete the `tmdb_review` / `youtube_review` line.", ""]
        for c in people[:100]:
            notes = "; ".join(x for x in [*(c.get("flags") or []), c.get("needs_review"), c.get("tmdb_review"),
                                          c.get("youtube_review")] if x)
            lines.append(f"- **{_md(c.get('name'))}** (`{c.get('slug')}`): {_md(notes)}")
    sources = (state.meta or {}).get("sources") or {}
    problems = [f"- `{k}`: {v.get('error') or v.get('reason')}" for k, v in sources.items()
                if isinstance(v, dict) and v.get("status") in ("error", "skipped")]
    if problems:
        lines += ["", "### Sources that didn't run", *problems]
    lines += ["", f"_Last run: {(state.meta or {}).get('last_run', 'never')}_"]
    return "\n".join(lines)


def parse_decisions(body: str) -> list[tuple[str, str, str | None]]:
    """Ticked boxes in the review issue -> [(candidate id, accept|reject|block|merge, merge target)]."""
    out, current = [], None
    for line in (body or "").splitlines():
        h = CAND_HEADER.match(line)
        if h:
            current = h[1]
            continue
        m = CHECKED.match(line)
        if not (m and current):
            continue
        text = m[1]
        if text.startswith(BOX_BLOCK):
            out.append((current, "block", None))
        elif text.startswith(BOX_REJECT):
            out.append((current, "reject", None))
        elif text.startswith(BOX_ACCEPT):
            out.append((current, "accept", None))
        elif text.startswith(BOX_MERGE):
            t = re.search(r"`([^`]+)`", text)
            if t:
                out.append((current, "merge", t[1]))
    # One decision per candidate: the strongest wins (block > reject > merge > accept).
    rank = {"block": 3, "reject": 2, "merge": 1, "accept": 0}
    best: dict[str, tuple[str, str, str | None]] = {}
    for d in out:
        if d[0] not in best or rank[d[1]] > rank[best[d[0]][1]]:
            best[d[0]] = d
    return list(best.values())


def apply_decisions(state: State, decisions) -> int:
    """Write decisions into overrides.yaml (in memory; the caller saves)."""
    n = 0
    for cid, action, target in decisions:
        if action == "accept":
            _append(state, "accept", cid)
        elif action in ("reject", "block"):
            _append(state, "reject", cid)
            ch = ((state.candidates.get(cid) or {}).get("channel") or {}).get("id")
            if action == "block" and ch:
                _append(state, "block_channels", ch)
        elif action == "merge" and target:
            if not any(list(m) == [cid, target] for m in state.override_list("merge")):
                state.overrides["merge"].append(CommentedSeq([cid, target]))
                state.overrides["merge"][-1].fa.set_flow_style()
        n += 1
    return n


def read_issue_decisions(http, token: str, repo_slug: str, state: State) -> int:
    """Apply boxes ticked in the open review issue. Returns how many were applied."""
    issues = http.get_json(f"{GITHUB_API}/repos/{repo_slug}/issues",
                           params={"labels": QUEUE_LABEL, "state": "open", "per_page": 10},
                           headers=_gh_headers(token))
    issues = [i for i in issues if "pull_request" not in i]
    if not issues:
        return 0
    return apply_decisions(state, parse_decisions(issues[0].get("body") or ""))


# --- GitHub -------------------------------------------------------------------

def _gh_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def update_issue(http, token: str, repo_slug: str, state: State) -> str:
    """Create or update the single 'Review queue (N pending)' issue. Returns its URL."""
    h = _gh_headers(token)
    title = f"Review queue ({len(state.candidates)} pending)"
    body = queue_markdown(state, repo_slug)
    issues = http.get_json(f"{GITHUB_API}/repos/{repo_slug}/issues",
                           params={"labels": QUEUE_LABEL, "state": "open", "per_page": 10}, headers=h)
    issues = [i for i in issues if "pull_request" not in i]
    if issues:
        issue = issues[0]
        if issue.get("title") != title or issue.get("body") != body:
            issue = http.send_json("PATCH", issue["url"], {"title": title, "body": body}, headers=h)
    else:
        issue = http.send_json("POST", f"{GITHUB_API}/repos/{repo_slug}/issues",
                               {"title": title, "body": body, "labels": [QUEUE_LABEL]}, headers=h)
    return issue.get("html_url", "")


FIELD_RE = re.compile(r"^###\s+(.+?)\s*$", re.M)


def parse_issue_form(body: str) -> dict:
    """GitHub issue forms render as '### Label\\n\\nvalue'."""
    out, parts = {}, FIELD_RE.split(body or "")
    for i in range(1, len(parts) - 1, 2):
        val = parts[i + 1].strip()
        out[parts[i].strip().lower()] = "" if val == "_No response_" else val
    return out


def fetch_reports(http, token: str, repo_slug: str, platforms) -> list[dict]:
    """Open `missing-special` issues as review candidates."""
    h = _gh_headers(token)
    issues = http.get_json(f"{GITHUB_API}/repos/{repo_slug}/issues",
                           params={"labels": REPORT_LABEL, "state": "open", "per_page": 100}, headers=h)
    out = []
    for i in issues:
        if "pull_request" in i:
            continue
        f = parse_issue_form(i.get("body") or "")
        title = f.get("title") or f.get("special title") or i.get("title", "").replace("Missing special:", "").strip()
        who = f.get("comedian") or f.get("comedian(s)") or ""
        url = f.get("link") or f.get("url") or ""
        plat = f.get("platform") or ""
        out.append(make_candidate(
            "report", f"report:{i['number']}",
            title=title, raw_title=title,
            performer_names=[n.strip() for n in re.split(r",|&| and ", who) if n.strip()],
            release_date=(f.get("release date") or "")[:10] or None,
            platforms=[platforms.entry(plat, url=url or None)] if plat else [],
            url=i.get("html_url"),
            evidence=["user_report"],
            trusted=False,
        ) | {"issue_number": i["number"]})
    return out


def close_resolved_reports(http, token: str, repo_slug: str, state: State) -> int:
    """Close report issues whose candidate you accepted, rejected or merged."""
    h = _gh_headers(token)
    decided = {str(x) for x in state.override_list("accept") + state.override_list("reject")}
    decided |= {str(m[0]) for m in state.override_list("merge") if m}
    issues = http.get_json(f"{GITHUB_API}/repos/{repo_slug}/issues",
                           params={"labels": REPORT_LABEL, "state": "open", "per_page": 100}, headers=h)
    closed = 0
    for i in issues:
        cid = candidate_id(f"report:{i['number']}")
        if cid in decided:
            verdict = "added" if cid not in state.override_list("reject") else "not added"
            http.send_json("POST", f"{i['url']}/comments",
                           {"body": f"Reviewed as `{cid}`: {verdict}. Thanks!"}, headers=h)
            http.send_json("PATCH", i["url"], {"state": "closed", "state_reason":
                           "completed" if verdict == "added" else "not_planned"}, headers=h)
            closed += 1
    return closed


def apply_removal_requests(http, token: str, repo_slug: str, state: State) -> int:
    """`not-a-special` issues (from the app's Remove button): hide the record for good, close the issue."""
    h = _gh_headers(token)
    issues = http.get_json(f"{GITHUB_API}/repos/{repo_slug}/issues",
                           params={"labels": REMOVE_LABEL, "state": "open", "per_page": 100}, headers=h)
    done = 0
    for i in issues:
        if "pull_request" in i:
            continue
        f = parse_issue_form(i.get("body") or "")
        sid = (f.get("special id") or "").strip().strip("`")
        resolved = state.resolve_id(sid) if sid else ""
        if resolved not in state.specials:
            http.send_json("POST", f"{i['url']}/comments", {"body": (
                f"Couldn't find a special with ID `{sid}`. Check the ID on the special's page and edit "
                "this issue; the next nightly run will try again.")}, headers=h)
            continue
        _append(state, "reject", resolved)
        extra = ""
        block = (f.get("also ignore its youtube channel?") or f.get("ignore channel") or "").lower()
        ch = (state.specials[resolved].get("ids") or {}).get("youtube_channel")
        if block.startswith("yes") and ch:
            _append(state, "block_channels", ch)
            extra = " Its YouTube channel is ignored from now on."
        http.send_json("POST", f"{i['url']}/comments", {"body": (
            f"Removed `{resolved}` from the database for good (added to `reject` in "
            f"`data/overrides.yaml`).{extra} It disappears from the app after this run deploys.")}, headers=h)
        http.send_json("PATCH", i["url"], {"state": "closed", "state_reason": "completed"}, headers=h)
        done += 1
    return done


# --- terminal review -----------------------------------------------------------

def interactive(state: State, ask=input, say=print) -> dict:
    """Walk the pending candidates and record decisions in overrides.yaml."""
    counts = {"accept": 0, "reject": 0, "merge": 0, "skip": 0}
    cands = sorted(state.candidates.values(), key=lambda c: c["id"])
    if not cands:
        say("Nothing to review.")
        return counts
    decided = {str(x) for x in state.override_list("accept") + state.override_list("reject")}
    decided |= {str(m[0]) for m in state.override_list("merge") if m}
    for n, c in enumerate(cands, 1):
        if c["id"] in decided:
            continue
        say("")
        say(f"[{n}/{len(cands)}] {c['id']}  ({c.get('source')})")
        say(f"  {', '.join(c.get('performer_names') or c.get('performers') or ['?'])} — {c.get('title')}")
        say(f"  raw: {c.get('raw_title')}")
        say(f"  date: {c.get('release_date') or '?'}   runtime: {c.get('runtime_min') or '?'} min")
        if c.get("url"):
            say(f"  {c['url']}")
        say(f"  why: {'; '.join(c.get('reasons') or [])}")
        match = c.get("match")
        if match and match in state.specials:
            s = state.specials[match]
            say(f"  possible match: {match} — {s.get('title')} ({s.get('release_date')})")
        prompt = "  [a]ccept  [r]eject  " + ("[m]erge into match  " if match else "") + \
                 "[i]nto other id  [s]kip  [q]uit > "
        choice = (ask(prompt) or "s").strip().lower()
        if choice == "q":
            break
        if choice == "a":
            _append(state, "accept", c["id"])
            counts["accept"] += 1
        elif choice == "r":
            _append(state, "reject", c["id"])
            counts["reject"] += 1
        elif choice in ("m", "i"):
            target = match if choice == "m" and match else (ask("  merge into special id: ") or "").strip()
            if target:
                state.overrides["merge"].append(CommentedSeq([c["id"], target]))
                state.overrides["merge"][-1].fa.set_flow_style()
                counts["merge"] += 1
        else:
            counts["skip"] += 1
    save_overrides(state)
    say(f"\nSaved to data/overrides.yaml: {counts}. Run `python -m specials nightly --sources none` to apply.")
    return counts


def _append(state: State, key: str, value: str) -> None:
    seq = state.overrides.get(key)
    if seq is None:
        seq = state.overrides[key] = CommentedSeq()
    if value not in seq:
        seq.append(value)
    try:
        # Short lists stay on one line; long ones go one per line so they're easy to edit on a phone.
        seq.fa.set_flow_style() if len(seq) <= 4 else seq.fa.set_block_style()
    except AttributeError:
        pass
