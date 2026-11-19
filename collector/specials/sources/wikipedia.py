"""Wikipedia "YYYY in stand-up comedy": dated English-language releases.

Only facts are stored (performer, title, date, platform) with a link back to the
page. Tables are read by their header names, so small layout changes on the
page don't break the parser. Rowspans (a date shared by several rows) are handled.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from ..util import iso, month_from_text, norm, parse_loose_date
from . import Context, make_candidate

API = "https://en.wikipedia.org/w/api.php"

COLUMNS = {
    "date": ["date", "release date", "released", "premiere", "premiere date", "air date"],
    "performer": ["comedian", "comedians", "comedian s", "performer", "performers", "artist",
                  "artists", "comic", "starring", "headliner"],
    "title": ["title", "special", "special title", "album"],
    "platform": ["network", "platform", "distributor", "network platform", "network/platform",
                 "streaming service", "service", "outlet", "label", "released on", "venue network"],
    "runtime": ["runtime", "length", "running time", "duration"],
    "kind": ["type", "format", "medium"],
}


class _Table:
    def __init__(self, heading: str):
        self.heading = heading
        self.rows: list[list[dict]] = []


class TableParser(HTMLParser):
    """Collects every <table class="wikitable"> as rows of cells {text, rowspan, colspan, header}."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[_Table] = []
        self.list_items: list[tuple[str, str]] = []   # (heading, text) fallback
        self._heading = ""
        self._in_heading = False
        self._heading_buf: list[str] = []
        self._depth = 0          # nested table depth inside a wikitable
        self._table: _Table | None = None
        self._row: list[dict] | None = None
        self._cell: dict | None = None
        self._skip = 0           # inside <sup class=reference>, <style>, etc.
        self._li: list[str] | None = None
        self._li_depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""
        if self._skip:
            if tag in ("sup", "style", "span", "script"):
                self._skip += 1
            return
        if tag in ("style", "script") or (tag == "sup" and "reference" in cls) or \
                (tag == "span" and ("mw-editsection" in cls or "sortkey" in cls)):
            self._skip = 1
            return
        if tag in ("h2", "h3", "h4"):
            self._in_heading = True
            self._heading_buf = []
        elif tag == "table":
            if self._table is not None:
                self._depth += 1
            elif "wikitable" in cls:
                self._table = _Table(self._heading)
        elif self._table is not None and self._depth == 0:
            if tag == "tr":
                self._row = []
            elif tag in ("td", "th") and self._row is not None:
                self._cell = {"text": [], "header": tag == "th",
                              "rowspan": _int(a.get("rowspan")), "colspan": _int(a.get("colspan"))}
            elif tag == "br" and self._cell is not None:
                self._cell["text"].append("\n")
        elif self._table is None and tag == "li":
            if self._li is None:
                self._li = []
            self._li_depth += 1
        elif self._table is None and self._li is not None and tag == "i":
            self._li.append("«")     # keep italics: on these pages the title is the italic text
        elif tag == "br" and self._cell is not None:
            self._cell["text"].append("\n")

    def handle_endtag(self, tag):
        if self._skip:
            if tag in ("sup", "style", "span", "script"):
                self._skip -= 1
            return
        if tag in ("h2", "h3", "h4") and self._in_heading:
            self._in_heading = False
            self._heading = " ".join("".join(self._heading_buf).split())
        elif tag == "table" and self._table is not None:
            if self._depth:
                self._depth -= 1
            else:
                self.tables.append(self._table)
                self._table = None
        elif self._table is not None and self._depth == 0:
            if tag in ("td", "th") and self._cell is not None and self._row is not None:
                raw = "".join(self._cell["text"])
                self._cell["text"] = "\n".join(" ".join(x.split()) for x in raw.split("\n")).strip()
                self._row.append(self._cell)
                self._cell = None
            elif tag == "tr" and self._row is not None:
                if self._row:
                    self._table.rows.append(self._row)
                self._row = None
        elif tag == "i" and self._table is None and self._li is not None:
            self._li.append("»")
        elif tag == "li" and self._li is not None:
            self._li_depth -= 1
            if self._li_depth == 0:
                self.list_items.append((self._heading, " ".join("".join(self._li).split())))
                self._li = None

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_heading:
            self._heading_buf.append(data)
        if self._cell is not None:
            self._cell["text"].append(data)
        elif self._li is not None:
            self._li.append(data)


def _int(v) -> int:
    try:
        return max(1, int(str(v).strip()))
    except (TypeError, ValueError):
        return 1


def grid(table: _Table) -> list[list[dict]]:
    """Expand rowspan/colspan into a rectangular grid of cells."""
    out: list[list[dict]] = []
    pending: dict[int, tuple[dict, int]] = {}   # col -> (cell, rows remaining)
    for row in table.rows:
        line: list[dict] = []
        col = 0
        cells = iter(row)
        while True:
            if col in pending:
                cell, left = pending[col]
                line.append(cell)
                if left <= 1:
                    del pending[col]
                else:
                    pending[col] = (cell, left - 1)
                col += 1
                continue
            cell = next(cells, None)
            if cell is None:
                break
            for _ in range(cell["colspan"]):
                line.append(cell)
                if cell["rowspan"] > 1:
                    pending[col] = (cell, cell["rowspan"] - 1)
                col += 1
        while col in pending:     # spans continuing past the last real cell
            cell, left = pending[col]
            line.append(cell)
            if left <= 1:
                del pending[col]
            else:
                pending[col] = (cell, left - 1)
            col += 1
        out.append(line)
    return out


def map_columns(header: list[str]) -> dict[str, int]:
    cols: dict[str, int] = {}
    for i, h in enumerate(header):
        n = norm(h)
        for key, names in COLUMNS.items():
            if key not in cols and (n in [norm(x) for x in names]):
                cols[key] = i
    return cols


def clean(text: str) -> str:
    text = re.sub(r"\[[^\]]*\]", "", text or "")
    return " ".join(text.replace("\n", " ").split()).strip(" ‡†*")


def split_names(text: str) -> list[str]:
    parts = re.split(r"\n|,|;|\s+&\s+|\s+and\s+|\s+with\s+", text or "")
    return [p for p in (clean(x) for x in parts) if p and not p.lower().startswith("various")]


def parse_page(html: str, year: int) -> list[dict]:
    """Return rows: {date, performers, title, platform, runtime, kind, heading}."""
    p = TableParser()
    p.feed(html)
    rows: list[dict] = []
    for t in p.tables:
        g = grid(t)
        if not g:
            continue
        header_idx = next((i for i, r in enumerate(g[:3]) if all(c["header"] for c in r)), 0)
        cols = map_columns([c["text"] for c in g[header_idx]])
        if "title" not in cols or "performer" not in cols:
            continue
        month_hint = month_from_text(t.heading)
        for r in g[header_idx + 1:]:
            if all(c["header"] for c in r) and len({id(c) for c in r}) == 1:
                month_hint = month_from_text(r[0]["text"]) or month_hint   # month divider rows
                continue

            def cell(key: str) -> str:
                i = cols.get(key)
                return r[i]["text"] if i is not None and i < len(r) else ""
            title = clean(cell("title")).strip('"“”')
            if not title:
                continue
            d = parse_loose_date(clean(cell("date")), default_year=year, default_month=month_hint)
            rt = re.search(r"(\d+)\s*(?:min|minutes)?", cell("runtime") or "")
            rows.append({
                "date": iso(d),
                "performers": split_names(cell("performer")),
                "title": title,
                "platform": clean(cell("platform")).split(" / ")[0] if cell("platform") else None,
                "runtime": int(rt[1]) if rt and cell("runtime") else None,
                "kind": clean(cell("kind")) or None,
                "heading": t.heading,
            })
    rows.extend(parse_list_items(p.list_items, year))
    return rows


_MONTH_NAMES = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE_PREFIX = re.compile(
    rf"^(?P<date>(?:{_MONTH_NAMES})\s+\d{{1,2}}(?:\s*[–-]\s*\d{{1,2}})?(?:,\s*\d{{4}})?)\s*[:–—-]\s*(?P<body>.+)$")
# "Jane Doe's one-hour special «Example Hour» is released on Netflix."
POSSESSIVE = re.compile(r"^(?P<who>[^«»]{2,90}?)(?:'s|’s|'|’)\s+(?P<desc>[^«»]{0,60}?)«(?P<title>[^»]+)»(?P<rest>.*)$")
# Typos seen on the pages: "Alex Fernándezs special «…»", "Are You Garbage special «…»"
_ADJ = r"(?:(?:one-hour|hour-long|half-hour|hour|debut|new|stand-up|standup|comedy|first|second|third|latest|netflix|hbo|youtube)\s+){0,2}"
LOOSE_POSSESSIVE = re.compile(rf"^(?P<who>[^«»]{{2,60}}?)s?\s+(?P<desc>{_ADJ}special)\s+«(?P<title>[^»]+)»(?P<rest>.*)$")
# No italics: "Ryan Goodcase's special Maybe They're Dead on YouTube."
PLAIN_TITLE = re.compile(r"^(?P<who>[^«»]{2,60}?)(?:'s|’s|'|’)\s+(?P<desc>(?:[\w-]+\s+){0,2}special)\s+"
                         r"(?P<title>[^«».]{2,80}?)(?P<rest>\s+(?:is released |premieres |aired )?(?:on|by)\s+.*)$")
# "D. L. Hughley: «Contrarian» is released on Netflix."
NAME_COLON = re.compile(r"^(?P<who>[^«»:]{2,60}):\s*«(?P<title>[^»]+)»(?P<rest>.*)$")
# "«D. L. Hughley: Contrarian» is released on Netflix."
TITLE_FIRST = re.compile(r"^«(?P<title>[^»]+)»(?P<rest>.*)$")
PLATFORM_RE = re.compile(
    r"\b(?:on|by|via|through|aired on|airs on)\s+(?:the\s+)?(?P<plat>[A-Z0-9][^.,;()«»]*?)"
    r"(?=\s+(?:in|at|with|and|as|after|for|from|on)\b|[.,;()]|$)")
NOT_A_RELEASE = re.compile(
    r"\b(wins?|won|nominat\w*|dies|died|announc\w*|launch\w*|publish\w*|unveil\w*|ranks?|tours?|touring|"
    r"donat\w*|acquir\w*|sues|arrested|hosts?|hosted|cancel\w*|record(?:s|ed)? a)\b", re.I)
NOT_A_SPECIAL_TITLE = re.compile(r"\b(prize|awards?|roast|tribute|honoring|gala|festival|best of)\b", re.I)
NON_SPECIAL_KINDS = re.compile(r"\b(documentary|series|podcast|book|memoir|film|movie|sitcom|show|tour|play)\b", re.I)
AUDIO_KINDS = re.compile(r"\b(album|ep|vinyl|record|audio)\b", re.I)


def parse_list_items(items: list[tuple[str, str]], year: int) -> list[dict]:
    """The yearly pages are prose bullets:

        January 15: Sebastian Maniscalco's special «Stay Hungry» on Netflix.
        January 2: Nick DiPaolo's one-hour special «Another Senseless Killing» is released on VHX.
        March 2: David Heti's album «And You Will Regret It» on Stand Up! Records.

    («» marks the italic title.) Events, awards and deaths share the same list and are skipped.
    """
    rows = []
    for heading, text in items:
        m = DATE_PREFIX.match(text.strip())
        if not m:
            continue
        body = m["body"].strip()
        d = parse_loose_date(re.sub(r"[–-]\s*\d{1,2}", "", m["date"]), default_year=year,
                             default_month=month_from_text(heading))
        pm = POSSESSIVE.match(body) or LOOSE_POSSESSIVE.match(body) or PLAIN_TITLE.match(body)
        verified = True
        if not pm and (nc := NAME_COLON.match(body)) and not NOT_A_RELEASE.search(nc["who"]):
            pm = {"who": nc["who"], "desc": "", "title": nc["title"], "rest": nc["rest"]}
        if pm:
            who, desc, title, rest = pm["who"], pm["desc"], pm["title"], pm["rest"]
            if NOT_A_RELEASE.search(who) or len(who.split()) > 10:
                continue
        else:
            tm = TITLE_FIRST.match(body)
            if not tm or ":" not in tm["title"]:
                continue
            who, title = (x.strip() for x in tm["title"].split(":", 1))
            desc, rest, verified = "", tm["rest"], False
        if NOT_A_RELEASE.search(desc) or NOT_A_SPECIAL_TITLE.search(title):
            continue
        kind = "audio" if AUDIO_KINDS.search(desc) else (
            "other" if NON_SPECIAL_KINDS.search(desc) and "special" not in desc.lower() else "special")
        first_sentence = re.split(r"(?<=[a-z0-9\)])\.\s", rest, maxsplit=1)[0]
        plat = PLATFORM_RE.search(first_sentence)
        performers = split_names(who)
        rows.append({
            "date": iso(d),
            "performers": performers,
            "title": clean(title).strip('"“”'),
            "platform": clean(plat["plat"]) if plat else None,
            "runtime": None,
            "kind": kind,
            "desc": clean(desc),
            "verified": verified,
            "showcase": who.strip().lower().startswith("various"),
            "heading": heading,
        })
    return rows


AUDIO_HINTS = ("album", "audio", "vinyl", "spotify", "podcast")


def collect(ctx: Context) -> list[dict]:
    cfg = ctx.config.collector("wikipedia")
    pattern = cfg.get("page_pattern", "{year}_in_stand-up_comedy")
    year_now = ctx.today.year
    if ctx.since_year:
        years = list(range(ctx.since_year, year_now + 1))
    else:
        years = [year_now - 1, year_now] if ctx.today.month <= 2 else [year_now]
    out: list[dict] = []
    for year in years:
        page = pattern.format(year=year)
        try:
            res = ctx.http.get_json(API, params={
                "action": "parse", "page": page, "prop": "text", "format": "json",
                "formatversion": "2", "redirects": "1"})
        except Exception as e:
            ctx.warn(f"wikipedia: {page}: {e}")
            continue
        if "error" in res:
            ctx.warn(f"wikipedia: {page}: {res['error'].get('info')}")
            continue
        html = (res.get("parse") or {}).get("text") or ""
        rows = parse_page(html, year)
        if not rows:
            ctx.warn(f"wikipedia: {page}: no releases recognized")
        url = f"https://en.wikipedia.org/wiki/{page}"
        for row in rows:
            out.append(row_to_candidate(ctx, row, page, url))
    return out


def row_to_candidate(ctx: Context, row: dict, page: str, url: str) -> dict:
    from ..util import contains_phrase, slugify

    performers = row["performers"]
    platforms = []
    if row.get("platform"):
        for name in re.split(r",|/|\n", row["platform"]):
            if clean(name):
                platforms.append(ctx.platforms.entry(clean(name), date=row.get("date")))
    hints = ctx.config.scope.get("showcase_title_hints", [])
    showcase = row.get("showcase") or len(performers) > 2 or any(contains_phrase(row["title"], h) for h in hints)
    kind_text = f"{row.get('kind') or ''} {row.get('heading') or ''}".lower()
    kind_text += " " + " ".join(re.findall(r"\(([^)]*)\)", row["title"].lower()))
    who = slugify(performers[0]) if performers else "unknown"
    return make_candidate(
        "wikipedia",
        f"wikipedia:{page[:4]}:{who}:{slugify(row['title'])}",
        title=row["title"],
        raw_title=row["title"],
        performer_names=performers,
        release_date=row.get("date"),
        runtime_min=row.get("runtime"),
        language=None,     # the yearly pages list releases worldwide; TMDB fills this in when it matches
        platforms=platforms,
        ids={"wikipedia": page},
        url=url,
        evidence=["wikipedia_list"]
        + (["audio"] if row.get("kind") == "audio" or any(h in kind_text for h in AUDIO_HINTS) else [])
        + (["not_a_special"] if row.get("kind") == "other" else [])
        + ([] if row.get("verified", True) else ["performer_unverified"]),
        showcase=showcase,
        trusted=True,
    )
