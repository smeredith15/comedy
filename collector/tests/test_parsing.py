from conftest import fixture_text

from specials.comedians import NameIndex, clean_seed_name
from specials.sources.wikipedia import parse_page
from specials.sources.youtube_feeds import parse_feed
from specials.titles import match_key, split_title
from specials.util import parse_iso_duration_minutes, parse_loose_date, slugify


def test_slugify():
    assert slugify("Ali Wong: Single Lady") == "ali-wong-single-lady"
    assert slugify("Beyoncé & Jay's Hour!") == "beyonce-and-jays-hour"


def test_durations_and_dates():
    assert parse_iso_duration_minutes("PT1H2M10S") == 62
    assert parse_iso_duration_minutes("PT45M") == 45
    assert parse_loose_date("January 6", default_year=2026).isoformat() == "2026-01-06"
    assert parse_loose_date("3 February 2025").isoformat() == "2025-02-03"
    assert parse_loose_date("12", default_year=2026, default_month=2).isoformat() == "2026-02-12"


def test_seed_cleanup_flags_shared_names():
    assert clean_seed_name("Jane Doe (Comedy)") == ("Jane Doe", ["name shared with another artist on Pandora (likely a musician)"])
    assert clean_seed_name("  Sam   Rivera ") == ("Sam Rivera", [])
    assert clean_seed_name("Flight & the Conchords")[1] == ["looks like a group or band name"]


def test_split_youtube_titles():
    idx = NameIndex([{"slug": "jane-doe", "name": "Jane Doe"}])
    assert split_title("Jane Doe | Example Hour (Full Comedy Special)", idx)[:2] == (["Jane Doe"], "Example Hour")
    assert split_title("Example Hour | Jane Doe | Full Special", idx)[:2] == (["Jane Doe"], "Example Hour")
    assert split_title("Jane Doe: Example Hour - Full Stand-Up Special", idx)[:2] == (["Jane Doe"], "Example Hour")
    assert split_title("Jane Doe Full Special: Example Hour", idx)[:2] == (["Jane Doe"], "Example Hour")
    # Channel owner as the hint, no name in the title
    p, t, known = split_title("Kitchen Table [Full Special]", None, hint_names=["Sam Rivera"])
    assert (p, t, known) == (["Sam Rivera"], "Kitchen Table", True)
    # Unknown performer on a distributor channel
    p, t, known = split_title("New Person | Big Debut | 800 Pound Gorilla", idx,
                              extra_noise=["800 Pound Gorilla"])
    assert (p, t, known) == (["New Person"], "Big Debut", False)


def test_match_key():
    assert match_key("Example Hour (Full Special)", ["Jane Doe"]) == "example hour"
    assert match_key("The Example Hour 2026", []) == "example hour"


def test_wikipedia_tables():
    rows = parse_page(fixture_text("wikipedia_2026.html"), 2026)
    titles = [(r["date"], r["performers"], r["title"], r["platform"]) for r in rows]
    assert titles[0] == ("2026-01-06", ["Jane Doe"], "Example Hour", "Netflix")
    assert titles[1] == ("2026-01-06", ["Sam Rivera"], "Kitchen Table", "YouTube")   # rowspan date
    assert titles[2][1] == ["Pat Example", "Lee Sample", "Chris Placeholder"]
    assert titles[3] == ("2026-02-03", ["Morgan Test"], "Loud Thoughts", "Prime Video")
    assert titles[4][0] == "2026-02-12"           # bare day + month heading
    assert len(rows) == 5                         # the Deaths table is ignored


def test_youtube_feed():
    entries = parse_feed(fixture_text("youtube_feed.xml"))
    assert [e["video_id"] for e in entries] == ["VIDkitchen1", "VIDpodcast1", "VIDjanefree"]
    assert entries[0]["published"] == "2026-01-06"
    assert entries[0]["channel_id"] == "UCsamrivera000000000000"
