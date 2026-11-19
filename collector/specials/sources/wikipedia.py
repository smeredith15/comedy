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
    if not rows:
        rows = parse_list_items(p.list_items, year)
    return rows


LIST_RE = re.compile(
    r"^(?P<date>[A-Z][a-z]+ \d{1,2})\s*[–—:-]\s*(?P<who>[^:]+?)\s*[:–—-]\s*(?P<title>.+?)"
    r"(?:\s*\((?P<platform>[^)]+)\))?$")


def parse_list_items(items: list[tuple[str, str]], year: int) -> list[dict]:
    """Fallback for pages that use bullet lists: 'January 5 – Jane Doe: Example Hour (Netflix)'."""
    rows = []
    for heading, text in items:
        m = LIST_RE.match(clean(text))
        if not m:
            continue
        d = parse_loose_date(m["date"], default_year=year, default_month=month_from_text(heading))
        rows.append({"date": iso(d), "performers": split_names(m["who"]), "title": clean(m["title"]),
                     "platform": m["platform"], "runtime": None, "kind": None, "heading": heading})
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
            ctx.warn(f"wikipedia: {page}: no release tables recognized")
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
    showcase = len(performers) > 2 or any(contains_phrase(row["title"], h) for h in hints)
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
        language="en",
        platforms=platforms,
        ids={"wikipedia": page},
        url=url,
        evidence=["wikipedia_list"] + (["audio"] if any(h in kind_text for h in AUDIO_HINTS) else []),
        showcase=showcase,
        trusted=True,
    )
