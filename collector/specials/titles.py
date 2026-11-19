"""Title cleanup: split "Performer: Title | Full Special" into performer and title."""

from __future__ import annotations

import re

from .util import norm

SEPARATORS = re.compile(r"\s+[|\-–—~/]{1,2}\s+|:\s+|\s+[|]\s*|\s*[|]\s+")
BRACKETS = re.compile(r"[\(\[\{]([^\)\]\}]*)[\)\]\}]")

NOISE = {
    "full", "special", "specials", "official", "stand", "up", "standup", "comedy", "comedian",
    "hour", "hd", "4k", "uncensored", "uncut", "new", "entire", "free", "video", "complete",
    "set", "the", "a", "an", "netflix", "youtube", "premiere", "world", "exclusive", "now",
    "streaming", "watch", "length", "and", "only", "on", "in", "is", "joke", "presents",
}
KEY_NOISE = {"special", "specials", "full", "standup", "stand", "official", "premiere", "uncensored",
             "netflix", "youtube", "exclusive"}
YEAR = re.compile(r"^(19|20)\d{2}$")


def _words(text: str) -> list[str]:
    return norm(text).split()


def is_noise(segment: str, extra: set[str] = frozenset()) -> bool:
    n = norm(segment)
    if not n:
        return True
    if n in extra:
        return True
    words = n.split()
    return all(w in NOISE or YEAR.match(w) for w in words) and any(
        w in KEY_NOISE for w in words)


def strip_edge_noise(segment: str) -> str:
    """Drop runs like 'Full Special' at either end of a segment."""
    raw = segment.split()
    if not raw:
        return segment

    def word(i: int) -> str:
        return norm(raw[i])

    end = len(raw)
    while end > 0 and (word(end - 1) in NOISE or YEAR.match(word(end - 1) or "x")):
        end -= 1
    if end < len(raw) and not any(norm(w) in KEY_NOISE for w in raw[end:]):
        end = len(raw)
    start = 0
    while start < end and word(start) in NOISE:
        start += 1
    if start and not any(norm(w) in KEY_NOISE for w in raw[:start]):
        start = 0
    out = " ".join(raw[start:end]).strip(" -–—|:,")
    return out or segment


def split_title(raw: str, index=None, hint_names: list[str] | None = None,
                extra_noise: list[str] | None = None) -> tuple[list[str], str, bool]:
    """Return (performer names, display title, performer_was_known).

    index:       NameIndex of known comedians (optional)
    hint_names:  performer we expect (e.g. the channel's comedian)
    extra_noise: distributor / platform names to drop as segments
    """
    extra = {norm(x) for x in (extra_noise or [])}
    text = raw or ""
    # Bracketed noise: "(Full Special)", "[Official Video]", "(2024)"
    text = BRACKETS.sub(lambda m: " " if is_noise(m[1], extra) or YEAR.match(m[1].strip()) else m[0], text)
    segments = [s.strip() for s in SEPARATORS.split(text) if s and s.strip()]
    segments = [strip_edge_noise(s) for s in segments if not is_noise(s, extra)]
    segments = [s for s in segments if norm(s) not in extra]

    performers: list[str] = []
    known = False
    rest: list[str] = []
    hints = {norm(h): h for h in (hint_names or [])}
    for s in segments:
        n = norm(s)
        name = None
        if n in hints:
            name = hints[n]
        elif index is not None and index.lookup(s):
            name = index.names.get(index.lookup(s), s)
            known = True
        if name and len(performers) < 4 and name not in performers:
            performers.append(name)
            if n in hints:
                known = True
        else:
            rest.append(s)

    if not performers and hint_names:
        performers = list(hint_names)
        known = True
        # "Jane Doe Example Hour" -> drop a leading hint name inside a segment
        for i, s in enumerate(rest):
            for h in hint_names:
                if norm(s).startswith(norm(h) + " "):
                    rest[i] = s[len(h):].strip(" -–—|:,")
    if not performers and len(rest) >= 2 and _looks_like_name(rest[0]):
        performers = [rest.pop(0)]

    title = ": ".join(rest).strip() if rest else (performers[0] if performers else (raw or "").strip())
    return performers, title, known


def _looks_like_name(s: str) -> bool:
    words = s.split()
    return 1 < len(words) <= 4 and all(w[:1].isupper() for w in words if w.isalpha())


def match_key(title: str, performer_names: list[str] = ()) -> str:
    """Aggressively normalized title for matching."""
    t = f" {norm(title)} "
    for name in performer_names:
        n = norm(name)
        if n and t.strip() != n:
            t = t.replace(f" {n} ", " ")
    for phrase in ("full special", "full comedy special", "stand up special", "standup special",
                   "comedy special", "full stand up", "official", "uncensored", "netflix special",
                   "live from", "live at", "live in"):
        t = t.replace(f" {phrase} ", " ")
    words = [w for w in t.split() if not YEAR.match(w)]
    if words and words[0] in ("the", "a", "an") and len(words) > 1:
        words = words[1:]
    return " ".join(words)
