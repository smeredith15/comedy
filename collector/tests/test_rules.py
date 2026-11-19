"""Rules added after the first real runs: Wikipedia prose pages, YouTube noise, review checkboxes,
removals, TMDB self-credits, and the gaps report."""
from conftest import ENV, TODAY, FakeHttp, fixture_text, tmdb_movie

from specials import comedians, gaps, pipeline, review
from specials.classify import classify
from specials.ids import candidate_id
from specials.pipeline import make_context
from specials.sources.wikipedia import parse_page
from specials.sources.youtube_api import video_candidate


def test_wikipedia_prose_page():
    rows = parse_page(fixture_text("wikipedia_prose.html"), 2026)
    got = [(r["date"], r["performers"], r["title"], r["platform"], r["kind"]) for r in rows]
    assert got == [
        ("2026-01-06", ["Jane Doe"], "Example Hour", "Netflix", "special"),
        ("2026-01-09", ["Sam Rivera"], "Kitchen Table", "YouTube", "special"),
        ("2026-01-12", ["Riley Demo"], "Spoken Album", "Stand Up! Records", "audio"),
        ("2026-02-02", ["Alex Fernández"], "The Best Comedian", "Netflix", "special"),   # missing apostrophe
        ("2026-02-03", ["Ryan Sample"], "Maybe Tomorrow", "YouTube", "special"),       # no italics
        ("2026-02-04", ["D. L. Placeholder"], "Contrarian Hour", "Netflix", "special"),
    ]   # skipped: death, award, "Various comedians" compilation, tour documentary, roast, See also


def _ctx(state, config, channel=None):
    ctx = make_context(state, config, None, TODAY)
    if channel:
        ctx.trusted_channels[channel["id"]] = channel
    return ctx


def _yt(ctx, config, title, runtime, ch_id="UCx", ch_title="Somebody"):
    c = video_candidate(ctx, "youtube_feed", "VID00000001", title, "2026-02-01", ch_id, ch_title,
                        {"runtime_min": runtime})
    c["performers"] = c["performer_names"]
    return classify(c, config.scope)


def test_youtube_noise_is_dropped(state, config):
    sam = {"id": "UCsam", "name": "Sam Rivera", "kind": "comedian", "comedian_name": "Sam Rivera",
           "comedian_slug": "sam-rivera"}
    state.comedians.append(comedians.new_comedian("Sam Rivera", tracked=True))
    state.comedians.append(comedians.new_comedian("Gary Placeholder", tracked=True))
    ctx = _ctx(state, config, sam)
    own = dict(ch_id="UCsam", ch_title="Sam Rivera")
    assert _yt(ctx, config, "Sam Rivera | Kitchen Table (Full Comedy Special)", 58, **own).action == "accept"
    # podcast with a guest: no "special" in the title → dropped, not queued
    assert _yt(ctx, config, "Gary Placeholder on Fatherhood & Starting Over | Whiskey Ginger", 82, **own).action == "reject"
    assert _yt(ctx, config, "Told an old lady off #standupcomedy", 1, **own).action == "reject"
    assert _yt(ctx, config, "Best of October | Sam Rivera", 23, **own).action == "reject"
    # re-upload spam from a random channel
    spam = _yt(ctx, config, "Famous Comic Funniest Roast EVER 😂🔥 || Full Stand Up Comedy 2026", 63)
    assert spam.action == "reject"
    # a comedian uploading their own special to their own channel
    self_up = _yt(ctx, config, "Yoni Sample: Fun Age | Full Comedy Special", 65, ch_id="UCyoni", ch_title="Yoni Sample")
    assert self_up.action == "accept", self_up.reasons
    # same special from an unknown channel still gets a look
    assert _yt(ctx, config, "Yoni Sample: Fun Age | Full Comedy Special", 65).action == "review"


def test_review_checkboxes_round_trip(state, config):
    c1 = {"id": "cand_00000001", "source": "youtube_search", "title": "A", "performer_names": ["X"],
          "channel": {"id": "UCspam", "title": "Spam"}, "reasons": ["untrusted"], "url": "https://y"}
    c2 = {"id": "cand_00000002", "source": "tmdb", "title": "B", "performer_names": ["Y"],
          "match": "y--b--2026", "reasons": ["partial"]}
    c3 = {"id": "cand_00000003", "source": "tmdb", "title": "C", "performer_names": ["Z"], "reasons": []}
    state.candidates = {c["id"]: c for c in (c1, c2, c3)}
    body = review.queue_markdown(state, "me/repo")
    assert body.count("- [ ] ") == 8
    ticked = (body.replace(f"- [ ] {review.BOX_BLOCK}", f"- [x] {review.BOX_BLOCK}")
                  .replace(f"- [ ] {review.BOX_MERGE}", f"- [X] {review.BOX_MERGE}"))
    lines, seen_c3 = [], False
    for line in ticked.splitlines():           # accept only the third one
        seen_c3 = seen_c3 or "cand_00000003" in line
        if seen_c3 and line == f"- [ ] {review.BOX_ACCEPT}":
            line, seen_c3 = f"- [x] {review.BOX_ACCEPT}", False
        lines.append(line)
    decisions = sorted(review.parse_decisions("\n".join(lines)))
    assert decisions == [("cand_00000001", "block", None), ("cand_00000002", "merge", "y--b--2026"),
                         ("cand_00000003", "accept", None)]
    review.apply_decisions(state, decisions)
    assert "cand_00000001" in state.override_list("reject")
    assert state.override_list("block_channels") == ["UCspam"]
    assert ["cand_00000002", "y--b--2026"] in [list(m) for m in state.override_list("merge")]
    assert state.override_list("accept") == ["cand_00000003"]

    # A later upload from the blocked channel is rejected without asking.
    later = {"id": "cand_00000009", "source": "youtube_search", "title": "D", "performer_names": ["X"],
             "channel": {"id": "UCspam"}, "evidence": ["title_hint"], "runtime_min": 60, "ids": {}, "platforms": []}
    report = pipeline.process(state, config, [later], TODAY)
    assert "cand_00000009" not in state.candidates and report.rejected_by_rules >= 1


def test_not_a_special_issue_hides_record(state):
    state.specials["jane-doe--x--2026"] = {"id": "jane-doe--x--2026", "title": "X", "performers": ["jane-doe"],
                                           "ids": {"youtube_channel": "UCpod"}, "platforms": [], "sources": []}
    body = "### Special ID\n\njane-doe--x--2026\n\n### Also ignore its YouTube channel?\n\nYes\n\n### Notes\n\n_No response_"
    http = FakeHttp({"/repos/me/repo/issues": [{"number": 7, "url": "https://api.github.com/repos/me/repo/issues/7",
                                                "body": body}]})
    assert review.apply_removal_requests(http, "tok", "me/repo", state) == 1
    assert state.override_list("reject") == ["jane-doe--x--2026"]
    assert state.override_list("block_channels") == ["UCpod"]
    assert http.calls[-1][0] == "PATCH" and http.calls[-1][2]["state"] == "closed"


def test_tmdb_resolves_everyone_and_finds_untagged_self_credits(repo, config, state):
    for n in ("Jane Doe", "Sam Rivera", "Lee Sample"):
        state.comedians.append(comedians.new_comedian(n, tracked=True))
    people = {"Jane Doe": 11, "Sam Rivera": 12, "Lee Sample": 13}
    untagged = tmdb_movie(201, "Lee Sample: Quiet Hour", ["Lee Sample"], 62, "2026-01-20", keyword=False)
    untagged["genres"] = [{"id": 35, "name": "Comedy"}]
    doc = tmdb_movie(202, "Lee Sample Goes Home", ["Lee Sample"], 85, "2026-01-25", keyword=False)
    doc["genres"] = [{"id": 99, "name": "Documentary"}]
    routes = {
        "/3/search/keyword": {"results": [{"id": 9716, "name": "stand-up comedy"}]},
        "/3/discover/movie": {"total_pages": 1, "results": []},
        "/3/search/person": lambda p: {"results": [{"id": people[p["query"]], "name": p["query"]}]},
        "/3/person/11/movie_credits": {"cast": []},
        "/3/person/12/movie_credits": {"cast": []},
        "/3/person/13/movie_credits": {"cast": [
            {"id": 201, "character": "Self", "genre_ids": [35], "release_date": "2026-01-20"},
            {"id": 202, "character": "Himself", "genre_ids": [99], "release_date": "2026-01-25"},
            {"id": 203, "character": "Detective Ray", "genre_ids": [80], "release_date": "2026-01-25"}]},
        "/3/movie/201": untagged, "/3/movie/202": doc,
    }
    pipeline.run(state, config, FakeHttp(routes), today=TODAY, env=ENV, sources=["tmdb"], resolve_limit=1)
    assert all(state.comedian(s)["tmdb_id"] for s in ("jane-doe", "sam-rivera", "lee-sample"))  # not capped at 1
    assert "lee-sample--quiet-hour--2026" in state.specials
    assert not any("goes-home" in s for s in state.specials)     # documentary dropped


def test_gaps_explains_local_state(state, config):
    state.comedians.append(comedians.new_comedian("Jane Doe", tracked=True))
    state.specials["jane-doe--example-hour--2026"] = {"id": "jane-doe--example-hour--2026", "title": "Example Hour",
                                                      "performers": ["jane-doe"], "release_date": "2026-01-06",
                                                      "ids": {}, "platforms": []}
    state.rejected["cand_x"] = {"id": "cand_x", "source": "tmdb", "performer_names": ["Jane Doe"],
                                "title": "Short Thing", "reasons": ["runtime 15 min"]}
    out = gaps.explain(state, "Jane Doe: Example Hour")
    assert "In the database" in out and "no TMDB ID" in out
    assert "dropped by a rule" in gaps.explain(state, "Jane Doe - Short Thing")
    assert "isn't in `data/comedians.yaml`" in gaps.explain(state, "Nobody Known: Whatever")
    report = gaps.coverage(state)
    assert "No TMDB ID yet (1)" in report


def test_rejections_are_logged_but_youtube_noise_is_not(state, config):
    tm = {"id": candidate_id("tmdb:5"), "source": "tmdb", "title": "Tiny", "performer_names": ["A"],
          "runtime_min": 12, "evidence": ["keyword"], "ids": {}, "platforms": []}
    yt = {"id": candidate_id("youtube:abc"), "source": "youtube_feed", "title": "clip", "performer_names": ["A"],
          "evidence": ["short"], "ids": {}, "platforms": []}
    pipeline.process(state, config, [tm, yt], TODAY)
    assert list(state.rejected) == [tm["id"]]
