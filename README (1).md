# specials-tracker

A self-updating database of stand-up comedy specials, plus an installable phone app (PWA) for tracking what you've seen and what you want to see, and for picking a special at random.

> **Status: design stage.** This README is the build plan. The commands, files and screens described below don't exist yet.

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

**Comedian list.** The starting list in `data/seeds/pandora_comedians.txt` comes from the Pandora station. The import step removes duplicates and strips suffixes like "(Comedy)" and "(Comedian)". It also flags names that are shared with musicians, or comedians who also release music, so you can check them once.

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
  "sources": ["https://…", "https://…"],
  "first_seen": "2026-03-01",
  "updated": "2026-04-14"
}
```

| File | Contents |
|---|---|
| `data/comedians.yaml` | Tracked comedians: name, aliases, TMDB person ID, YouTube channel ID, followed flag. You can edit it by hand |
| `data/specials.jsonl` | The finished records |
| `data/candidates.jsonl` | Possible specials waiting for review |
| `data/overrides.yaml` | Your manual decisions (accept, reject, merge, edit). The job applies these after its own rules |
| `data/redirects.json` | Merged IDs mapped to the record that replaced them |
| `data/meta.json` | Time and counts of the last run |

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

`python -m specials review` gives you the same review on a computer.

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

**Planned stack:** Vite + TypeScript + Preact, `vite-plugin-pwa` (Workbox) for offline support, Dexie for IndexedDB.

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
│   │   ├── sources/          # tmdb.py, wikipedia.py, youtube_feeds.py,
│   │   │                     # youtube_search.py, news.py, watchmode.py
│   │   ├── classify.py       # scope rules
│   │   ├── match.py          # dedupe / merge
│   │   ├── ids.py            # stable slugs, redirects
│   │   ├── store.py          # jsonl/yaml ↔ SQLite cache
│   │   ├── review.py         # review queue + GitHub issue
│   │   └── export.py         # JSON for the app
│   └── tests/
├── app/                      # the PWA
│   ├── index.html
│   ├── public/               # manifest.webmanifest, icons
│   └── src/
└── .github/
    ├── workflows/
    │   ├── nightly.yml       # collect → commit → build → deploy
    │   └── pages.yml         # build + deploy (reusable; also runs on push)
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
python -m specials backfill --since 2017  # one-time history load
python -m specials nightly                # collect → classify → match → export
python -m specials review                 # review pending candidates on a computer

# app
cd ../app
npm install
npm run dev                               # serves the app using the data export
npm run build
```

### 4. Nightly job
- **Schedule:** `23 9 * * *`, which is about 4:23 AM Eastern.
- **Steps:** collect → classify → match → apply `overrides.yaml` → export → commit `data/` → build and deploy the app → update the review issue.
- **Deploy happens inside the nightly job.** Commits pushed with the default `GITHUB_TOKEN` don't trigger other workflows, so `nightly.yml` runs `pages.yml` itself as a reusable workflow.
- **There's a commit every night.** `meta.json` changes on each run, which also keeps GitHub from turning off the schedule in a quiet repo.
- **Permissions** are declared in the workflow file: `contents: write`, `pages: write`, `id-token: write`, `issues: write`.

---

## Terms and attribution

- **TMDB:** the About screen shows the TMDB logo and the line *"This product uses the TMDB API but is not endorsed or certified by TMDB."*
- **Wikipedia:** only facts are stored (performer, title, date, platform), with a link back to the page. No article text is copied.
- **YouTube:** follows the YouTube API Services Terms and Developer Policies. Only video IDs, titles, lengths and publish dates are stored, and YouTube records are re-checked regularly.
- Personal, non-commercial project.

---

## Roadmap

- **v1:** TMDB, Wikipedia and YouTube collectors, the review queue, and the app (browse, lists, follow, Spin, backup).
- **v1.1:** AI-assisted extraction from news feeds, Watchmode availability checks, and the missing-special issue flow.
- **v1.2:** syncing your lists across devices (for example through a private GitHub Gist) and alerts for new specials from comedians you follow.
- **Later:** specials in other languages, audio-only comedy albums, and a link to the Spotify comedy playlist project. A new special is the clearest sign a comedian is "hot," and a first special from a comedian who isn't on the list is a discovery candidate.
