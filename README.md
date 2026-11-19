# specials-tracker

A self-updating database of stand-up comedy specials, plus an installable phone app (PWA) for tracking what you've seen and what you want to see, and for picking a special at random.

> **Status: v1 built.** The collector, data files, app and workflows below are in the repo. The database fills in on the first nightly run, once the API keys are set (see [Setup](#setup)). Items marked v1.1 or later are still stubs.

---

## What it does

- **Finds new specials every night.** It pulls from TMDB, Wikipedia and YouTube (news feeds come later), merges duplicates and publishes one clean list.
- **Phone app (PWA).** You install it from the browser. You can browse new, upcoming and older specials and mark each one *Want to see*, *Seen* (with date, rating and notes) or *Not interested*. You can also follow comedians.
- **Spin.** A random picker that respects filters like "unseen only", "under 45 minutes" or "on services I have".
- **Your lists stay on your phone.** The specials database is public information. What you've watched is stored only on your device, and you can export it as a backup file.

---

## How it works

```
nightly GitHub Action
┌────────────────────────────────────────────────────────────────────┐
│  collect  →  candidates  →  classify    →  match/merge  →  export   │
│  TMDB          (raw)        (is it a       (one record     (JSON    │
│  Wikipedia                   special?)      per special)    for app)│
│  YouTube feeds                   │                                  │
│  YouTube search                  └─ unsure → review queue           │
│  News (v1.1)                                                        │
└────────────────────────────────────────────────────────────────────┘
        │ commits data/*.jsonl                 │ builds + deploys
        ▼                                      ▼
  git history = change log            GitHub Pages → PWA on your phone
```

**Git is the database.** The finished records are kept as sorted text files, so each night's commit shows exactly what was added or changed. A SQLite file is built locally and in CI as a working cache. It is git-ignored.

---

## Data sources

| Source | What it catches | Access |
|---|---|---|
| **TMDB** | Specials on streaming services and TV (Netflix, Max, Prime Video, Hulu, Peacock, Paramount+…), with announced dates, runtimes, IMDb IDs and where to watch | Free API token (non-commercial use) |
| **Wikipedia** "YYYY in stand-up comedy" | Dated English-language releases, including YouTube. The yearly pages go back to at least 2017, which covers the backfill | MediaWiki API, no key |
| **YouTube channel RSS** | New uploads from tracked comedians and distributors | No key, no quota |
| **YouTube Data API** | Video length (`videos.list`), channel lookup by handle (`channels.list`), and a few searches a day for comedians nobody is tracking yet (`search.list` has a small daily cap) | Free API key |
| **News / press RSS** (v1.1) | Announcements and less common platforms (Veeps, Patreon, comedians' own sites) | Free. Turning articles into records needs an extraction step |
| **Watchmode** (optional) | Second check on streaming availability | Free developer tier |

**Comedian list.** The starting list in `data/seeds/pandora_comedians.txt` comes from the Pandora station. The import step removes duplicates and strips suffixes like "(Comedy)" and "(Comedian)". It also flags names you should check once: a "(Comedy)" suffix means Pandora had another artist with that name, usually a musician, and names that look like a band or group are flagged too. Comedians who also release music can't be detected automatically. Mark any you know with a flag in `comedians.yaml`.

**Distributors.** These are channels watched no matter who is performing, such as 800 Pound Gorilla, Comedy Central Stand-Up, Don't Tell Comedy, Comedy Dynamics and Spesh. The list lives in `config/sources.yaml`.

---

## Scope: what counts as a special

These are v1 defaults in `config/scope.yaml`. All of them can be changed.

```yaml
language: en                  # English-language only for v1
region: US                    # where-to-watch region
min_runtime_minutes: 25
formats: [hour, half_hour]    # solo specials; half-hours are labeled as such
include_showcases: false      # multi-comic showcase episodes
include_audio_albums: false   # audio-only releases (later)

youtube:
  # A YouTube video is only accepted automatically if it comes from a tracked
  # comedian's channel or a known distributor. Anything else goes to review.
  trusted_channels_only: true
  title_hints_positive: ["special", "full special", "stand-up", "standup", "full hour"]
  title_hints_negative: ["podcast", "episode", "clip", "compilation", "reacts", "interview", "trailer"]
```

Early-access releases are kept as one record with two dates. An example is a special that appears on a paid platform before going free on YouTube.

---

## Data model

`data/specials.jsonl` has one special per line, sorted by `id`:

```json
{
  "id": "jane-doe--example-hour--2026",
  "title": "Example Hour",
  "performers": ["jane-doe"],
  "status": "released",
  "format": "hour",
  "runtime_min": 58,
  "language": "en",
  "release_date": "2026-03-10",
  "public_release_date": "2026-04-14",
  "platforms": [
    {"platform": "800-pound-gorilla", "kind": "early_access", "url": "https://…"},
    {"platform": "youtube", "kind": "free", "url": "https://www.youtube.com/watch?v=…"}
  ],
  "ids": {"tmdb": null, "imdb": null, "youtube": "…", "wikipedia": "2026_in_stand-up_comedy"},
  "alt_ids": ["youtube:…"],
  "sources": ["https://…", "https://…"],
  "first_seen": "2026-03-01",
  "updated": "2026-04-14"
}
```

| File | Contents |
|---|---|
| `data/comedians.yaml` | Comedians: name, aliases, TMDB person ID, YouTube channel ID, `tracked` (checked nightly) and `followed` (pre-followed in the app) flags. Performers the collectors discover are added with `tracked: false`. You can edit it by hand |
| `data/specials.jsonl` | The finished records |
| `data/candidates.jsonl` | Possible specials waiting for review |
| `data/overrides.yaml` | Your manual decisions (accept, reject, merge, edit). The job applies these after its own rules |
| `data/redirects.json` | Merged IDs mapped to the record that replaced them |
| `data/meta.json` | Time and counts of the last run |

Small additions to the record: each platform entry can carry its own `date` (used to work out `public_release_date`), `alt_ids` keeps the TMDB/YouTube IDs of records merged into this one, and `"hidden": true` marks a record you rejected (it stays so re-collection lands on it, but the app doesn't show it).

**IDs never change.** A special keeps its ID even if its title is corrected later. When two records are merged, the old ID goes into `redirects.json`, and the app uses it to move your Seen and Want-to-see marks to the surviving record.

---

## Matching and review

- **Match:** each candidate is compared to existing records on performer, title and date. Titles are cleaned first: the "Name:" prefix, "Full Special", "| Netflix" and punctuation are removed. Dates count as matching within ±45 days, because announcements, early access and public release often fall on different days.
- **Merge automatically:** same performer and a very close title. **Review:** a partial title match, a YouTube video from an untrusted channel, or a runtime close to the cutoff.
- **Review from your phone:** each night the job updates one GitHub issue, titled *Review queue (N pending)*, that lists the candidate IDs. You decide by editing `data/overrides.yaml` in GitHub's web editor:

```yaml
accept: [cand_8f3a2c]
reject: [cand_19bd04]
merge:
  - [cand_77e1aa, jane-doe--example-hour--2026]
edit:
  jane-doe--example-hour--2026:
    format: half_hour
```

`python -m specials review` gives you the same review on a computer. `reject` also takes a special ID (hides the record), and `merge` takes `[special_id, special_id]` to fold one record into another.

The issue also lists comedians to check once: names Pandora shared with another artist, and unsure TMDB/YouTube matches from `comedians resolve`.

---

## The app (PWA)

**Screens**
- **Home:** new this month, upcoming, and new from comedians you follow.
- **Browse / search:** filter by platform, comedian, year, format, runtime, free only, and unseen only.
- **Special:** watch links, Want to see / Seen / Not interested, rating, notes, and watch dates (rewatches are fine).
- **Comedian:** every special by that comedian, plus a Follow button.
- **My lists:** Want to see, Seen, Not interested.
- **Spin:** the random picker (described below).
- **Settings:** your streaming services, region, backup and restore, and a manual data refresh.

**Spin**

| Setting | Options |
|---|---|
| Pool | Want to see · Any unseen · Everything |
| Max runtime | e.g. "I have 45 minutes" |
| Availability | Only my services · Free only · Anything |
| Also | Era, format, skip comedians you've watched in the last N days |

The default weights can be edited in Settings. *Want to see* counts ×3, a followed comedian ×2, a release in the last 90 days ×1.5, and a special you skipped in an earlier spin ×0.5. After a spin, the buttons are **Watch** (opens the platform link), **Spin again**, **Not tonight** (lowers that special's weight) and **Mark seen**.

**Storage and offline**
- Your lists are stored in IndexedDB on the phone. The app asks for persistent storage so Android doesn't clear it to free up space.
- **Export / Import** saves and restores a JSON backup file.
- The app and the last downloaded database are cached, so browsing and Spin work offline. New data loads in the background.

**Missing a special?** *Report missing special* opens a pre-filled GitHub issue (label `missing-special`). The nightly job adds those issues to the review queue.

**Install on Android:** open the GitHub Pages URL in Chrome, then tap ⋮ → **Install app** (or **Add to Home screen**).

**Stack:** Vite + TypeScript + Preact (+ signals), `vite-plugin-pwa` (Workbox) for the offline app shell, Dexie for IndexedDB. The app downloads `data/db.json` itself and keeps the last copy in IndexedDB, so it opens instantly offline and swaps in new data when it arrives.

---

## Repository layout

```
.
├── README.md
├── config/
│   ├── scope.yaml            # what counts as a special
│   ├── sources.yaml          # collectors on/off, distributor channels, news feeds
│   └── platforms.yaml        # platform names, normalization, icons
├── data/
│   ├── seeds/pandora_comedians.txt
│   ├── comedians.yaml
│   ├── specials.jsonl
│   ├── candidates.jsonl
│   ├── overrides.yaml
│   ├── redirects.json
│   └── meta.json
├── collector/                # Python package `specials`
│   ├── pyproject.toml
│   ├── .env.example
│   ├── specials/
│   │   ├── __main__.py       # CLI
│   │   ├── sources/          # tmdb.py, wikipedia.py, youtube_feeds.py, youtube_search.py,
│   │   │                     # youtube_api.py (shared), news.py + watchmode.py (v1.1 stubs)
│   │   ├── pipeline.py       # collect → classify → match → overrides
│   │   ├── classify.py       # scope rules
│   │   ├── match.py          # dedupe / merge
│   │   ├── titles.py         # "Name: Title | Full Special" cleanup
│   │   ├── comedians.py      # seed import, name lookup, TMDB/YouTube resolution
│   │   ├── ids.py            # stable slugs, redirects
│   │   ├── store.py          # jsonl/yaml ↔ SQLite cache
│   │   ├── review.py         # review queue + GitHub issue + missing-special reports
│   │   └── export.py         # JSON for the app
│   └── tests/                # pytest, against fixture data (no network)
├── app/                      # the PWA
│   ├── index.html
│   ├── public/icons/         # app icons (manifest is generated by vite-plugin-pwa)
│   ├── scripts/              # sample-data.mjs (fictional data for trying the app), make-icons.mjs
│   └── src/                  # pages/, components/, logic.ts (+ tests), store.ts, db.ts
└── .github/
    ├── workflows/
    │   ├── nightly.yml       # collect → commit → build → deploy (also the one-time backfill)
    │   ├── pages.yml         # build + deploy (reusable; also runs on push)
    │   └── ci.yml            # tests on pull requests and branches
    └── ISSUE_TEMPLATE/
        └── missing-special.yml
```

---

## Setup

### 1. Repository and Pages
1. Create the repo as **public**. On a free GitHub account, Pages only works with public repos. That's fine here: the database is all public information, and your lists never leave your phone.
2. Go to **Settings → Pages → Source** and choose **GitHub Actions**.

### 2. API keys
Add these under **Settings → Secrets and variables → Actions**:

| Secret | Where to get it | Needed |
|---|---|---|
| `TMDB_READ_TOKEN` | themoviedb.org → Settings → API ("API Read Access Token") | v1 |
| `YOUTUBE_API_KEY` | Google Cloud Console → enable *YouTube Data API v3* → Credentials | v1 |
| `WATCHMODE_API_KEY` | api.watchmode.com | optional |
| `ANTHROPIC_API_KEY` | console.anthropic.com (used for AI extraction from news articles) | v1.1 |

### 3. Local development
```bash
# collector (Python 3.12+)
cd collector
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                      # add TMDB_READ_TOKEN, YOUTUBE_API_KEY

python -m specials comedians import ../data/seeds/pandora_comedians.txt
python -m specials comedians resolve      # find TMDB person + YouTube channel; unsure matches → review
python -m specials sources resolve        # look up the distributor channel IDs from their handles
python -m specials backfill --since 2017  # one-time history load
python -m specials nightly                # collect → classify → match → export
python -m specials review                 # review pending candidates on a computer
python -m specials queue                  # print the review queue
python -m specials export                 # write app/public/data/db.json
pytest                                    # tests (no network needed)

# app
cd ../app
npm install
npm run dev                               # serves the app using the data export
npm run dev:sample                        # or: try it with a small FICTIONAL sample database
npm test
npm run build
```

### 4. First run
1. Paste the Pandora list into `data/seeds/pandora_comedians.txt`, run the `comedians import` command above and commit.
2. Merge to `main`. Scheduled workflows only run from the default branch.
3. **Actions → nightly → Run workflow** with `backfill_since` set to `2017` for the one-time history load. After that the schedule takes over.
4. Optional: download the TMDB logo from themoviedb.org/about/logos-attribution and save it as `app/public/icons/tmdb.svg`. The About screen shows it next to the attribution line.

### 5. Nightly job
- **Schedule:** `23 9 * * *`, which is about 4:23 AM Eastern.
- **Steps:** collect → classify → match → apply `overrides.yaml` → export → commit `data/` → build and deploy the app → update the review issue.
- **Deploy happens inside the nightly job.** Commits pushed with the default `GITHUB_TOKEN` don't trigger other workflows, so `nightly.yml` runs `pages.yml` itself as a reusable workflow.
- **There's a commit every night.** `meta.json` changes on each run, which also keeps GitHub from turning off the schedule in a quiet repo.
- **Permissions** are declared in the workflow file: `contents: write`, `pages: write`, `id-token: write`, `issues: write`.

---

## Terms and attribution

- **TMDB:** the About screen shows the TMDB logo and the line *"This product uses the TMDB API but is not endorsed or certified by TMDB."* Where-to-watch data comes from JustWatch through TMDB and is credited the same way.
- **Wikipedia:** only facts are stored (performer, title, date, platform), with a link back to the page. No article text is copied.
- **YouTube:** follows the YouTube API Services Terms and Developer Policies. Only video IDs, titles, lengths and publish dates are stored, and YouTube records are re-checked regularly.
- Personal, non-commercial project.

---

## Roadmap

- **v1:** TMDB, Wikipedia and YouTube collectors, the review queue, and the app (browse, lists, follow, Spin, backup).
- **v1.1:** AI-assisted extraction from news feeds, Watchmode availability checks, and the missing-special issue flow.
- **v1.2:** syncing your lists across devices (for example through a private GitHub Gist) and alerts for new specials from comedians you follow.
- **Later:** specials in other languages, audio-only comedy albums, and a link to the Spotify comedy playlist project. A new special is the clearest sign a comedian is "hot," and a first special from a comedian who isn't on the list is a discovery candidate.
