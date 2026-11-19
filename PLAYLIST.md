# Comedy playlist builder

Part of **specials-tracker**. It builds a private Spotify playlist that refreshes on a schedule, from the same comedian list the specials database uses (`data/comedians.yaml`, described in [README.md](README.md#comedian-list-shared)). Each refresh mixes classics, active stalwarts, comedians who are hot right now, the rest of your list, and a few new discoveries. It learns from the tracks you like and remove, so it works roughly like a Pandora station.

> **Status: design stage.** This document is the build plan. The commands and files below don't exist yet.

---

## What it does

- **Rebuilds one private playlist every week,** about 150 tracks (roughly 8–10 hours). You play it in the normal Spotify app, including on Android Auto.
- **Mixes five categories** using weights you set: Stalwarts, Classics, Hot, Core and Discoveries.
- **Learns from you:** a liked track boosts that comedian, and a track you remove from the playlist counts as a thumbs-down.
- **Adds a few new comedians each week** on probation. Liking any of their tracks moves them onto your list for good.
- **Shares the comedian list with the specials tracker.** A comedian you add in either place is used by both.

---

## How it works

```
nightly (inside the existing nightly.yml)
┌──────────────────────────────────────────────────────────────────────┐
│ sync      read the playlist, liked status, recently played → feedback│
│ catalog   refresh albums/tracks for 1/7 of comedians (new releases)  │
│ metrics   Last.fm listeners + Wikipedia page views for 1/7 of them   │
│ discover  score new-comedian candidates                              │
└──────────────────────────────────────────────────────────────────────┘
weekly (Sunday run, or "Run workflow" by hand)
┌──────────────────────────────────────────────────────────────────────┐
│ build     categorize → pick → space out → replace playlist contents  │
│           → update description with the mix                          │
└──────────────────────────────────────────────────────────────────────┘
```

Refreshing the catalog and the popularity numbers a seventh of the list at a time keeps each night well under Spotify's quota.

---

## What Spotify's API allows

Personal apps run in Spotify's **Development Mode**. As of November 2026:

| Available | Removed or limited |
|---|---|
| Create a playlist (`POST /me/playlists`), replace or add its items (`/playlists/{id}/items`) | **Artist top tracks** (removed) |
| An artist's albums, an album's tracks, single album/track lookups | **Popularity and follower counts** (removed from responses) |
| Liked-status check (`GET /me/library/contains`) | **Recommendations and related artists** (gone for new apps since Nov 2024) |
| Recently played (last 50 plays) | **Batch lookups** like `GET /albums?ids=` (removed, so one request per item) |
| Album and track `external_ids` (UPC/ISRC) | **Search** returns at most 10 results per request |
| | Artist **genres** are sparse and unreliable |

Other rules:
- The app owner needs Premium, and the app allows up to 5 users.
- The usage quota is shared across the whole developer account. When a request is refused with `429 QUOTA_EXCEEDED`, the job stops making Spotify calls for that run and picks up where it left off the next night.
- Spotify login tokens expire **6 months after you first authorize the app.** You'll re-authorize twice a year, and the job reminds you (see [Setup](#setup)).

Since Spotify no longer exposes popularity or recommendations, those come from Last.fm, Wikipedia and the specials database instead.

Spotify changes these rules often, so re-check its Web API changelog if something breaks.

---

## Signals

| Signal | Source | Used for |
|---|---|---|
| Albums, tracks, release dates, lengths | Spotify | Everything (the track catalog) |
| Original release date | MusicBrainz (album UPC lookup, then artist + title search) | Classics: correcting reissue and remaster dates |
| Listener and play counts, tags, similar artists, top tracks | Last.fm API | Stalwarts, Discoveries, picking a comedian's best-known tracks |
| Daily page views | Wikipedia page views API | Hot: spotting spikes |
| New specials, first-time specials | `data/specials.jsonl` (the specials database) | Hot, Discoveries |
| Likes, removals, plays | Spotify (your own account) | Feedback |

---

## Categories

Each track gets **one** category per build. Where more than one fits, the first match in this order wins: Discovery → Hot → Classic → Stalwart → Core.

| Category | Definition (defaults) | Share |
|---|---|---|
| **Stalwarts** | Comedian in the top quarter of *your list* by Last.fm listeners, first release 10 or more years ago, and a release or special in the last 5 years | 30% |
| **Classics** | Track first released 25 or more years ago (a rolling cutoff: 2001 or earlier in 2026) | 25% |
| **Hot** | Comedian has a new album or special in the last 12 months, **or** Wikipedia views over the last 14 days are at least 2× their 180-day median, **or** Last.fm listeners grew 15% or more in 8 weeks (once 8 weeks of history exist) | 20% |
| **Core** | Every other track from your list | 15% |
| **Discoveries** | Comedians on probation (see below) | 10% |

The cutoffs are measured against your own list, not against all artists, because comedians have far fewer listeners than musicians. If a category doesn't have enough eligible tracks, its leftover slots go to Core first, then to Stalwarts.

**Which tracks within a category**
- **Stalwarts and Classics:** about 60% from the comedian's Last.fm top tracks (matched to Spotify by title) and 40% deeper cuts.
- **Hot:** tracks from the newest release first.
- **Discoveries:** the comedian's 1–2 best-known tracks, or the opening tracks of their newest album.
- **Core:** random.

---

## Picking and spacing tracks

- **Per comedian:** at most 2 tracks per build (Hot comedians can have 3), and never two by the same comedian within 8 tracks of each other.
- **Repeats:** no track that appeared in the last 4 builds. Liked tracks can come back after 2 builds and are twice as likely to be picked.
- **Length:** skip tracks over 12 minutes (whole specials uploaded as one track) and under 30 seconds. Skip titles like "Intro", "Outro" or "Applause".
- **Duplicate bits:** when the same bit appears on several releases (the album, the special's audio, a "Best of"), only the earliest release is used. Compilations are skipped unless they're the only source.
- **Spacing:** categories are spread through the playlist, and Discoveries are never back to back.
- **Play with shuffle off.** The order is already mixed.

---

## Discovery and feedback

**Where new comedians come from**
1. Last.fm similar artists for comedians on your list. Each candidate must carry a comedy or stand-up tag.
2. Last.fm's top artists for the `stand-up comedy` / `comedy` tags, filtered to low listener counts.
3. Specials database: performers with a special in the last 12 months who aren't on your list.
4. Comedians you add by hand as `probation`.

Every candidate must have real comedy material on Spotify. Each build adds up to **3** of them as probation comedians, with 1–2 tracks each.

| What you do in Spotify | Effect |
|---|---|
| ❤️ Like a track | The track is boosted. A probation comedian is promoted to `tracked` (`added_by: discovery`) |
| Remove a track from the playlist | The track is banned from future builds and the comedian gets a strike |
| Remove a probation comedian's track | That comedian is dropped (`removed`) |
| Two strikes on a tracked comedian within 90 days | Muted in the playlist (`playlist: false`). Specials tracking continues, and you can undo it by editing the file |
| Probation comedian played 3 times with no like or removal | Dropped quietly and not suggested again for a year |
| Skip a track | Nothing. Skipping is not a thumbs-down |

Plays are read from Spotify's recently played list each night. It only returns the last 50 plays, so on heavy listening days a track that stayed in the playlist all week is counted as played.

---

## Configuration: `config/playlist.yaml`

```yaml
playlist:
  name: "Stand-Up Shuffle"
  public: false
  target_tracks: 150
  rebuild_day: sunday
  description_template: "Refreshed {date} · {counts}"

mix:                      # shares must add up to 100
  stalwarts: 30
  classics: 25
  hot: 20
  core: 15
  discoveries: 10

rules:
  max_tracks_per_comedian: 2
  max_tracks_per_hot_comedian: 3
  min_gap_same_comedian: 8
  repeat_cooldown_builds: 4
  liked_cooldown_builds: 2
  liked_weight: 2.0
  min_track_seconds: 30
  max_track_minutes: 12
  skip_title_patterns: ["^intro$", "^outro$", "applause"]
  skip_compilations: true

categories:
  classic_min_age_years: 25
  stalwart_listener_percentile: 75
  stalwart_min_career_years: 10
  stalwart_active_within_years: 5
  hot_release_within_days: 365
  hot_pageview_ratio: 2.0
  hot_lastfm_growth_pct: 15

discovery:
  per_build: 3
  tracks_each: 2
  required_tags: ["comedy", "stand-up comedy", "stand-up", "standup"]
  max_listener_percentile: 25
  neutral_appearances_before_drop: 3
  resuggest_after_days: 365

feedback:
  strikes_to_mute: 2
  strike_window_days: 90
  probation_strikes_to_drop: 1
```

Per-comedian settings live in `data/comedians.yaml`:

```yaml
- id: jane-doe
  name: Jane Doe
  playlist:
    weight: 1.0            # >1 picked more often, <1 less often
    exclude_albums: []     # Spotify album IDs to ignore (wrong artist, music album, etc.)
    music_ok: false        # set true for comedians whose comedy songs you want
```

---

## Data files

| File | Contents | Public? |
|---|---|---|
| `data/comedians.yaml` | The shared list, statuses and per-comedian settings | Yes |
| `data/playlist/catalog/{comedian-id}.json` | Cached albums and tracks, with original release dates | Yes |
| `data/playlist/metrics.jsonl` | Last.fm listener and Wikipedia page-view snapshots over time | Yes |
| `data/playlist/state.json.enc` | Build history, likes, removals, strikes, plays, Spotify auth date | **Encrypted** |

The repo is public so the specials app can be hosted on GitHub Pages. Your track-level feedback stays private because the state file is encrypted with `PLAYLIST_STATE_KEY`. The comedian list itself, including who was promoted or removed, is visible.

---

## Setup

### 1. Spotify app
1. Go to developer.spotify.com → **Dashboard** → **Create app** and choose **Web API**.
2. Set the Redirect URI to `http://127.0.0.1:8888/callback`. Spotify requires the loopback IP here; `localhost` won't work.
3. Copy the **Client ID** and **Client Secret**.

### 2. Last.fm
Create an API account at last.fm/api/account/create and copy the **API key**.

### 3. Secrets
Add these under **Settings → Secrets and variables → Actions**:

| Secret | Value |
|---|---|
| `SPOTIFY_CLIENT_ID` | From step 1 |
| `SPOTIFY_CLIENT_SECRET` | From step 1 |
| `SPOTIFY_REFRESH_TOKEN` | From step 4 |
| `LASTFM_API_KEY` | From step 2 |
| `PLAYLIST_STATE_KEY` | Printed by `python -m specials playlist keygen` |
| `GH_SECRETS_TOKEN` | Optional. A fine-grained GitHub token with **Secrets: read/write** on this repo only. If Spotify hands back a new refresh token, the job uses this to save it |

### 4. Authorize (once, then about every 6 months)
```bash
cd collector
python -m specials playlist auth        # opens a browser, captures the code, prints a refresh token
gh secret set SPOTIFY_REFRESH_TOKEN     # paste it in
```
The job records the authorization date. It opens a GitHub issue **14 days before** the token expires, and again if Spotify starts refusing it.

### 5. First run
```bash
python -m specials playlist init        # creates the private playlist and saves its ID
python -m specials playlist catalog     # first full catalog load; may take several nights because of quota
python -m specials playlist metrics
python -m specials playlist build --dry-run   # prints the mix without touching Spotify
python -m specials playlist build
```

---

## CLI

| Command | What it does |
|---|---|
| `playlist auth` / `keygen` / `init` | One-time setup |
| `playlist catalog [--comedian ID]` | Fetch or refresh albums and tracks |
| `playlist metrics` | Update the Last.fm, Wikipedia and specials-database signals |
| `playlist sync` | Read likes, removals and plays from Spotify |
| `playlist discover` | List discovery candidates and why each was picked |
| `playlist build [--dry-run]` | Choose tracks, print the category mix and update the playlist |
| `playlist report` | Coverage report: comedians with no or few Spotify tracks, category sizes, ambiguous artist matches |

Every command is run as `python -m specials …`.

**Schedule:** `sync`, plus a seventh of the comedians for `catalog` and `metrics`, runs every night. `build` runs on `rebuild_day`. To rebuild by hand, use **Actions → nightly → Run workflow** (this works from the GitHub mobile app).

---

## Known gaps

- **Spotify's comedy catalog has holes.** Some comedians' albums were pulled in rights disputes. `playlist report` lists comedians with little or nothing on Spotify.
- **Last.fm has thin data for some comedians.** That's why the cutoffs are relative to your list, and why discovery candidates must carry a comedy tag.
- **There's no Spotify-powered discovery.** Spotify's recommendation endpoints are gone, so new names come from Last.fm, the specials database and your own additions.
- **Name collisions.** A musician with the same name can get matched to a comedian. Matching is checked once when the comedian is added, unclear matches go to review, and `exclude_albums` fixes anything that slips through.
- **Removing a track always counts as a thumbs-down.** Skip instead if you just aren't in the mood.

---

## Terms

- **Spotify Developer Terms:** personal, non-commercial use. No Spotify data is sent to AI models; the terms prohibit feeding Spotify content into machine-learning or AI systems.
- **Last.fm:** follow its API terms (non-commercial use, reasonable request rate).
- **MusicBrainz:** at most 1 request per second, with a descriptive User-Agent.
- **Wikimedia:** a descriptive User-Agent on page-view requests.

---

## Roadmap

- **v1:** catalog, metrics, the five categories, feedback, discovery and the weekly build.
- **v1.1:** a playlist screen in the app showing this week's mix and the discovery candidates.
- **Later:** extra playlist variants ("Discoveries only", "Classics hour") and playlists for other people on your Spotify account (Development Mode allows up to 5 users).
