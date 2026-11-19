import json

from conftest import ENV, TODAY, FakeHttp, fixture_text, tmdb_movie, tmdb_routes, wiki_routes
from ruamel.yaml.comments import CommentedSeq

from specials import comedians, export, pipeline, review
from specials.classify import classify
from specials.ids import candidate_id
from specials.store import load_state, save_state

SAM_CHANNEL = "UCsamrivera000000000000"


def seed(state, tmp_path):
    f = tmp_path / "seed.txt"
    f.write_text("# header\nJane Doe (Comedy)\nSam Rivera\nsam rivera\n")
    stats = comedians.import_seed(state, f)
    assert stats == {"added": 2, "duplicates": 1, "flagged": 1}
    state.comedian("sam-rivera")["youtube_channel_id"] = SAM_CHANNEL


def routes(extra_search=True):
    movies = [
        tmdb_movie(101, "Jane Doe: Example Hour", ["Jane Doe"], 58, "2026-01-06"),
        tmdb_movie(102, "Morgan Test: Loud Thoughts", ["Morgan Test"], 61, "2026-02-03", ["Amazon Prime Video"]),
        tmdb_movie(103, "Upcoming Person: Future Hour", ["Upcoming Person"], None, "2026-06-01", ()),
        tmdb_movie(104, "Otro Especial", ["Persona Uno"], 60, "2026-01-15", lang="es"),
    ]
    r = tmdb_routes(movies)
    r.update(wiki_routes({2026: fixture_text("wikipedia_2026.html")}))
    r["/feeds/videos.xml"] = lambda p: fixture_text("youtube_feed.xml")
    durations = {"VIDkitchen1": "PT52M", "VIDpodcast1": "PT1H30M", "VIDjanefree": "PT40M",
                 "VIDunknown1": "PT48M"}

    def videos(params):
        return {"items": [{"id": v, "contentDetails": {"duration": durations[v]},
                           "snippet": {"defaultAudioLanguage": "en"}}
                          for v in params["id"].split(",") if v in durations]}
    r["/youtube/v3/videos"] = videos
    r["/youtube/v3/search"] = {"items": [{
        "id": {"videoId": "VIDunknown1"},
        "snippet": {"title": "Unknown Comic | Debut Hour | Full Special", "publishedAt": "2026-02-19T00:00:00Z",
                    "channelId": "UCrandom", "channelTitle": "Random Uploads"}}] if extra_search else []}
    return r


def run(state, config, **kw):
    return pipeline.run(state, config, FakeHttp(routes()), today=TODAY, env=ENV,
                        sources=["tmdb", "wikipedia", "youtube_feeds", "youtube_search"], **kw)


def test_nightly_end_to_end(repo, config, state, tmp_path):
    seed(state, tmp_path)
    report = run(state, config)
    assert all(v["status"] == "ok" for v in report.sources.values()), report.sources

    ids = sorted(state.specials)
    assert ids == ["jane-doe--example-hour--2026", "morgan-test--loud-thoughts--2026",
                   "sam-rivera--kitchen-table--2026", "upcoming-person--future-hour--2026"]

    jane = state.specials["jane-doe--example-hour--2026"]
    assert jane["ids"]["tmdb"] == "101" and jane["ids"]["wikipedia"] == "2026_in_stand-up_comedy"
    assert jane["format"] == "hour" and jane["runtime_min"] == 58 and jane["status"] == "released"
    assert [p["platform"] for p in jane["platforms"]] == ["netflix"]
    assert len(jane["sources"]) == 2

    sam = state.specials["sam-rivera--kitchen-table--2026"]
    assert sam["ids"]["youtube"] == "VIDkitchen1" and sam["runtime_min"] == 52
    yt = [p for p in sam["platforms"] if p["platform"] == "youtube"]
    assert len(yt) == 1 and yt[0]["url"].endswith("VIDkitchen1") and yt[0]["kind"] == "free"

    assert state.specials["upcoming-person--future-hour--2026"]["status"] == "upcoming"
    assert state.specials["morgan-test--loud-thoughts--2026"]["platforms"][0]["platform"] == "prime-video"

    # Only the untrusted search hit waits for review.
    assert list(state.candidates) == [candidate_id("youtube:VIDunknown1")]
    cand = state.candidates[candidate_id("youtube:VIDunknown1")]
    assert "YouTube video from an untrusted channel" in cand["reasons"]

    # Untracked performers were added to comedians.yaml.
    assert state.comedian("morgan-test")["tracked"] is False
    assert state.meta["counts"]["specials"] == 4

    md = review.queue_markdown(state, "me/repo")
    assert "1 candidate(s) waiting" in md and "Unknown Comic" in md
    assert "Jane Doe" in md and "Comedians to check" in md   # (Comedy) suffix flag


def test_second_run_is_stable_and_overrides_apply(repo, config, state, tmp_path):
    seed(state, tmp_path)
    run(state, config)
    save_state(state)
    first = (repo.data / "specials.jsonl").read_text()

    state = load_state(repo)
    run(state, config)
    save_state(state)
    assert (repo.data / "specials.jsonl").read_text() == first   # nothing changes on a quiet night

    cid = candidate_id("youtube:VIDunknown1")
    state = load_state(repo)
    state.overrides["accept"].append(cid)
    state.overrides["edit"]["jane-doe--example-hour--2026"] = {"format": "half_hour", "title": "Example Hour!"}
    state.overrides["merge"].append(CommentedSeq(["upcoming-person--future-hour--2026",
                                                  "morgan-test--loud-thoughts--2026"]))
    state.overrides["reject"].append("sam-rivera--kitchen-table--2026")
    run(state, config)
    save_state(state)

    assert "unknown-comic--debut-hour--2026" in state.specials
    assert state.candidates == {}
    jane = state.specials["jane-doe--example-hour--2026"]
    assert jane["format"] == "half_hour" and jane["title"] == "Example Hour!"   # id never changes
    assert state.redirects == {"upcoming-person--future-hour--2026": "morgan-test--loud-thoughts--2026"}
    assert "upcoming-person--future-hour--2026" not in state.specials
    assert state.specials["sam-rivera--kitchen-table--2026"]["hidden"] is True

    # Re-collecting the merged TMDB movie lands on the surviving record, not a new one.
    state = load_state(repo)
    run(state, config)
    assert "upcoming-person--future-hour--2026" not in state.specials
    assert state.specials["morgan-test--loud-thoughts--2026"]["ids"]["tmdb"] == "102"

    db = export.build(state, config)
    exported = {s["id"] for s in db["specials"]}
    assert "sam-rivera--kitchen-table--2026" not in exported      # hidden
    assert db["redirects"]["upcoming-person--future-hour--2026"] == "morgan-test--loud-thoughts--2026"
    assert db["comedians"]["jane-doe"]["name"] == "Jane Doe"
    assert db["platforms"]["netflix"]["name"] == "Netflix"
    path = export.write(state, config, tmp_path / "out")
    assert json.loads(path.read_text())["version"] == 1


def test_rejected_candidate_stays_rejected(repo, config, state, tmp_path):
    seed(state, tmp_path)
    run(state, config)
    cid = candidate_id("youtube:VIDunknown1")
    state.overrides["reject"].append(cid)
    run(state, config)
    assert cid not in state.candidates
    assert not any(s["ids"].get("youtube") == "VIDunknown1" for s in state.specials.values())


def test_partial_match_goes_to_review(repo, config, state, tmp_path):
    seed(state, tmp_path)
    run(state, config)
    c = {"id": "cand_test0001", "source": "wikipedia", "title": "Example Hour Part Two",
         "performer_names": ["Jane Doe"], "release_date": "2026-01-20", "platforms": [],
         "ids": {}, "trusted": True, "evidence": ["wikipedia_list"], "language": "en"}
    pipeline.process(state, config, [c], TODAY)
    assert state.candidates["cand_test0001"]["match"] == "jane-doe--example-hour--2026"
    assert any("partial title match" in r for r in state.candidates["cand_test0001"]["reasons"])


def test_classify_rules(config):
    scope = config.scope
    base = {"source": "tmdb", "title": "X", "performer_names": ["A"], "evidence": ["keyword"]}
    assert classify(base | {"runtime_min": 60}, scope).action == "accept"
    assert classify(base | {"runtime_min": 15}, scope).action == "reject"
    assert classify(base | {"runtime_min": 26}, scope).action == "review"      # near the cutoff
    assert classify(base | {"language": "fr"}, scope).action == "reject"
    assert classify(base | {"showcase": True}, scope).action == "reject"
    assert classify(base | {"evidence": []}, scope).action == "review"
    yt = {"source": "youtube_feed", "title": "X", "performer_names": ["A"], "trusted": True,
          "evidence": ["title_hint"], "runtime_min": 55}
    assert classify(yt, scope).action == "accept"
    assert classify(yt | {"trusted": False}, scope).action == "review"
    assert classify(yt | {"evidence": ["title_hint", "negative_title_hint"]}, scope).action == "reject"
    assert classify(yt | {"runtime_min": None}, scope).action == "review"


def test_missing_source_keys_are_reported(repo, config, state):
    report = pipeline.run(state, config, FakeHttp(routes()), today=TODAY, env={},
                          sources=["tmdb", "youtube_search", "news"])
    assert report.sources["tmdb"] == {"status": "skipped", "reason": "TMDB_READ_TOKEN not set"}
    assert report.sources["youtube_search"]["status"] == "skipped"
    assert report.sources["news"]["status"] == "disabled"


def test_issue_form_parsing():
    body = "### Comedian\n\nJane Doe\n\n### Title\n\nNew Hour\n\n### Platform\n\nVeeps\n\n### Release date\n\n_No response_"
    f = review.parse_issue_form(body)
    assert f == {"comedian": "Jane Doe", "title": "New Hour", "platform": "Veeps", "release date": ""}


def test_github_issue_update(state):
    http = FakeHttp({"/repos/me/repo/issues": []})
    url = review.update_issue(http, "tok", "me/repo", state)
    assert url.startswith("https://github.com/")
    method, _, body = http.calls[-1]
    assert method == "POST" and body["title"] == "Review queue (0 pending)" and body["labels"] == ["review-queue"]
