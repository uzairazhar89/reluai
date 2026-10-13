"""Positioned lines → one searchable text with headings, paragraphs and a page map.

PDFs store lines, not paragraphs or headings, so these are reconstructed from geometry:

* **Running headers and footers** (the same text at the top or bottom of many pages, page
  numbers) are removed so they do not pollute every passage.
* **Headings**: lines set clearly larger than the body text, plus short standalone bold or
  capitalised lines. They become Markdown headings, so the chunker records the heading path
  ("2 Audience › 2.1 Roles") of every passage. If more than a third of the lines look like
  headings (slides, forms) the weaker signals are ignored.
* **Paragraphs**: a new paragraph starts at a larger vertical gap, a bullet, an indented
  first line, or after a short line ending a sentence. Lines are joined, and words broken
  by a hyphen at a line end are rejoined unless the document shows the hyphen is part of
  the word ("context-specific"). A paragraph that runs onto the next page stays whole.

``page_starts`` records where each page begins in the text, so any passage (an exact span of
the text, see ``reluai_retrieval.chunking``) maps back to the page or pages it came from.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Literal

from reluai_docs.pdfread import RawPage

_LIGATURES = str.maketrans(
    {
        "ﬀ": "ff",
        "ﬁ": "fi",
        "ﬂ": "fl",
        "ﬃ": "ffi",
        "ﬄ": "ffl",
        "ﬅ": "st",
        "ﬆ": "st",
        " ": " ",
        " ": " ",
        " ": " ",
        " ": " ",
        "­": "",  # soft hyphen
    }
)
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f￾￿�]")
_SPACES = re.compile(r"\s+")
_LEADER = re.compile(r"\s*(?:[.·…_]\s?){4,}\s*")  # table-of-contents dot leaders
_PAGE_NUMBER = re.compile(r"^(?:page\s+)?[-–]?\s*\d{1,4}\s*[-–]?(?:\s*(?:of|/)\s*\d{1,4})?$", re.I)
_BULLET = re.compile(r"^(?:[•●▪◦‣∙○■□➢►–—*]|-(?=\s))")
# "2." / "(b)" list markers and "MAP 1.2:"-style item labels start a paragraph only after a
# finished sentence; otherwise they are a number that wrapped to the start of a line.
_NUMBERED_ITEM = re.compile(
    r"^(?:\(?\d{1,2}[.)](?=\s)|\(?[a-z]\)(?=\s)|[A-Z][A-Z-]+\s\d+(?:\.\d+)*:)"
)
_ENDS_SENTENCE = re.compile(r"[.!?:;\"”’)\]]$")
_DIGITS = re.compile(r"\d+")
_INNER_SENTENCE = re.compile(r"[a-z]{2}[.!?]\s+[A-Z]")  # "… is complex. Humans …"
_NUMBERING = re.compile(r"^(\d+(?:\.\d+)*)\.?\s|^(?:Part|Chapter|Appendix|Annex|Section)\b", re.I)
_TOC_ENTRY = re.compile(r"(?:\s|…)(?:\d{1,3}|[ivxlc]{1,6})$", re.IGNORECASE)
_SECTION_NUMBER = re.compile(
    r"^(?:\d+(?:\.\d+)*\.?|[A-Z]\.|(?:Part|Chapter|Section|Appendix)\b)\s*", re.I
)
_WORD = re.compile(r"[A-Za-z]+(?:-[A-Za-z]+)*")
_BROKEN_END = re.compile(r"([A-Za-z]+)-$")  # "… the context-"
_BROKEN_START = re.compile(r"[a-z]+")  # "specific laws …"

HeadingKind = Literal["size", "bold", "caps"]
MAX_HEADING_SHARE = 0.35


def clean_text(text: str) -> str:
    text = _SPACES.sub(" ", _CONTROL.sub("", text.translate(_LIGATURES))).strip()
    return _LEADER.sub(" … ", text).strip()


@dataclass(frozen=True, slots=True)
class OutlineEntry:
    level: int
    title: str
    page: int


@dataclass(frozen=True, slots=True)
class BuiltDocument:
    text: str
    page_starts: list[int]  # page_starts[i] = offset where page i + 1 starts in ``text``
    outline: list[OutlineEntry] = field(default_factory=list)
    truncated: bool = False

    @property
    def pages(self) -> int:
        return len(self.page_starts)

    def page_of(self, offset: int) -> int:
        """1-based page number containing ``offset``."""
        return max(1, bisect_right(self.page_starts, offset))

    def pages_for(self, start: int, end: int) -> tuple[int, int]:
        return self.page_of(start), self.page_of(max(start, end - 1))


@dataclass(slots=True)
class _Line:
    text: str
    top: float
    bottom: float
    x0: float
    x1: float
    size: float
    bold: bool
    keep_hyphen: bool = False  # the line ends in a compound's hyphen, not a word break

    @property
    def height(self) -> float:
        return max(1.0, self.bottom - self.top)


@dataclass(slots=True)
class _Block:
    kind: Literal["heading", "para", "label"]  # "label" only inside _run_in_labels
    lines: list[_Line]
    page: int
    level: int = 0

    @property
    def text(self) -> str:
        out = self.lines[0].text
        for prev, ln in pairwise(self.lines):
            if _broken_word(out, ln.text) and not prev.keep_hyphen:
                out = out[:-1] + ln.text
            elif _broken_word(out, ln.text):
                out += ln.text
            else:
                out = f"{out} {ln.text}"
        return out


def _broken_word(text: str, after: str) -> bool:
    """``text`` ends with a hyphen right after a letter and ``after`` goes on in lower case."""
    return len(text) > 1 and text.endswith("-") and text[-2].isalpha() and after[:1].islower()


def _mark_compound_hyphens(pages: list[list[_Line]]) -> None:
    """Decide, for each line ending in "word-", whether the hyphen belongs to the word.

    Most line-end hyphens break a word ("manage-" + "ment"), but some are a compound's own
    hyphen ("context-" + "specific"). With no dictionary, the document decides: the form it
    uses elsewhere wins ("context-specific" within a line, or "contextspecific"); failing
    that, the hyphen stays when both halves are words the document uses on their own.
    """
    lines = [ln for page in pages for ln in page]
    words: Counter[str] = Counter()
    for i, ln in enumerate(lines):
        text = ln.text
        if i and _BROKEN_END.search(lines[i - 1].text):
            text = _BROKEN_START.sub("", text, count=1)  # not a word on its own
        m = _BROKEN_END.search(text)
        if m:
            text = text[: m.start()]
        words.update(w.lower() for w in _WORD.findall(text))
    for ln, nxt in pairwise(lines):
        end, start = _BROKEN_END.search(ln.text), _BROKEN_START.match(nxt.text)
        if end is None or start is None:
            continue
        a, b = end.group(1).lower(), start.group(0)
        used_hyphenated = f"{a}-{b}" in words
        halves_are_words = min(len(a), len(b)) > 2 and a in words and b in words
        ln.keep_hyphen = used_hyphenated or (a + b not in words and halves_are_words)


# --------------------------------------------------------------------------- headers/footers
def _key(text: str) -> str:
    return _DIGITS.sub("#", text.lower())


def _strip_running(
    pages: list[list[_Line]], heights: list[float], body: float
) -> list[list[_Line]]:
    """Drop lines repeated in the top or bottom margin of many pages, and page numbers.

    Only the two outermost lines at each end of a page are candidates, and only inside the
    outer 12% of the page: running headers and footers live in the margins, while text that
    merely repeats in the body (a recurring table heading) is kept. Page numbers ("Page 3",
    "- 3 -") and text repeated exactly are dropped there. Short text that repeats only once
    numbers are ignored ("Report 2023 | 7") must sit in the outer 8%, and is kept if it is
    set as large as a heading ("Chapter 3" at the top of a page).
    """
    edges: list[set[int]] = []
    exact: Counter[str] = Counter()
    numbered: Counter[str] = Counter()
    for lines, height in zip(pages, heights, strict=True):
        order = sorted(range(len(lines)), key=lambda i: lines[i].top)
        margin = 0.12 * height
        edge = {
            i
            for i in order[:2] + order[-2:]
            if lines[i].top < margin or lines[i].bottom > height - margin
        }
        edges.append(edge)
        exact.update({lines[i].text.lower() for i in edge})
        numbered.update({_key(lines[i].text) for i in edge})
    # Seen on 40% of pages and at least 3 (2 in a two-page document, exact text only).
    threshold = max(3, int(0.4 * len(pages) + 0.999)) if len(pages) > 2 else 2
    if len(pages) < 2:
        exact = Counter()
    if len(pages) < 3:
        numbered = Counter()

    def running(ln: _Line, height: float) -> bool:
        if _PAGE_NUMBER.match(ln.text) or exact[ln.text.lower()] >= threshold:
            return True
        outer = ln.top < 0.08 * height or ln.bottom > 0.92 * height
        short = len(ln.text) <= 60
        return outer and short and numbered[_key(ln.text)] >= threshold and ln.size < body * 1.18

    return [
        [ln for i, ln in enumerate(lines) if not (i in edge and running(ln, height))]
        for lines, edge, height in zip(pages, edges, heights, strict=True)
    ]


# --------------------------------------------------------------------------- headings
def _body_size(pages: list[list[_Line]]) -> float:
    weights: Counter[float] = Counter()
    for lines in pages:
        for ln in lines:
            weights[round(ln.size * 2) / 2] += len(ln.text)
    if not weights:
        return 10.0
    size = weights.most_common(1)[0][0]
    return size if size > 0 else 10.0


def _heading_kind(ln: _Line, body: float) -> HeadingKind | None:
    t = ln.text
    if not 2 <= len(t) <= 120 or t[-1] in ",;-":
        return None
    letters = sum(ch.isalpha() for ch in t)
    if letters < 3 or letters / len(t) < 0.35:
        return None
    if ln.size >= body * 1.18:
        return "size"
    weak_ok = not t[:1].islower() and not _INNER_SENTENCE.search(t)
    if weak_ok and len(t) <= 80 and not t.endswith(".") and abs(ln.size - body) <= body * 0.25:
        if ln.bold:
            return "bold"
        if t.isupper() and letters >= 4:
            return "caps"
    return None


# --------------------------------------------------------------------------- paragraphs
def _typical_pitch(lines: list[_Line], body: float) -> float:
    """Median distance between consecutive lines of the same size: the page's line spacing."""
    steps = sorted(
        ln.top - prev.top
        for prev, ln in pairwise(lines)
        if abs(ln.size - prev.size) < 0.5 and 0.8 * ln.size < ln.top - prev.top < 2.5 * ln.size
    )
    return steps[len(steps) // 2] if steps else 1.2 * body


def _starts_paragraph(prev: _Line, ln: _Line, right_edge: float, pitch: float) -> bool:
    step = ln.top - prev.top
    size = max(prev.size, ln.size, 1.0)
    ends = bool(_ENDS_SENTENCE.search(prev.text))
    if step < -0.5 * size:
        # The next column: a sentence cut mid-way continues there.
        return ends or not ln.text[:1].islower()
    if step > pitch + 0.35 * size:
        return True  # extra space between paragraphs
    if _BULLET.match(ln.text) or (ends and _NUMBERED_ITEM.match(ln.text)):
        return True
    if ends and ln.x0 - prev.x0 > 0.8 * size:
        return True  # indented first line
    return ends and prev.x1 < right_edge - 3 * size  # a short line closing a paragraph


def _continues_heading(prev: _Line, ln: _Line) -> bool:
    """A wrapped heading: same size, the next line down, same alignment, no new number."""
    if abs(prev.size - ln.size) >= 0.6 or not 0 < ln.top - prev.top <= 1.4 * ln.size:
        return False
    if _SECTION_NUMBER.match(ln.text):
        return False
    same_left = abs(prev.x0 - ln.x0) < 2
    same_right = abs(prev.x1 - ln.x1) < 2
    same_centre = abs((prev.x0 + prev.x1) - (ln.x0 + ln.x1)) < 4
    return same_left or same_right or same_centre


def _page_blocks(
    lines: list[_Line], page: int, body: float, kinds: dict[int, HeadingKind], use_weak: bool
) -> list[_Block]:
    """Group a page's lines into headings and paragraphs.

    A short bold or capitalised line ("weak" heading signal) that follows a finished
    sentence (or extra space) and is not continued by lower-case text ends the paragraph
    before it and starts its own block, even at normal line spacing, because run-in headings
    are often set that way; it becomes a heading if it stands alone (or wraps onto a second
    such line) and is short.
    """
    blocks: list[_Block] = []
    right_edge = max((ln.x1 for ln in lines), default=0.0)
    pitch = _typical_pitch(lines, body)

    candidates = {id(ln) for ln in lines if use_weak and kinds.get(id(ln)) in ("bold", "caps")}
    standalone: set[int] = set()
    for i, ln in enumerate(lines):
        if id(ln) not in candidates:
            continue
        prev = lines[i - 1] if i else None
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        spaced = prev is None or ln.top - prev.top > pitch + 0.35 * max(ln.size, 1.0)
        after_sentence = prev is not None and (
            bool(_ENDS_SENTENCE.search(prev.text)) or id(prev) in candidates
        )
        # Body text carries on after it ("… output from the / MAP and MEASURE / functions")
        runs_on = (
            nxt is not None
            and nxt.text[:1].islower()
            and nxt.top - ln.top <= pitch + 0.35 * max(ln.size, 1.0)
            and id(nxt) not in candidates
        )
        if (spaced or after_sentence) and not runs_on:
            standalone.add(id(ln))

    def weak(ln: _Line) -> bool:
        return id(ln) in standalone

    for i, ln in enumerate(lines):
        kind = kinds.get(id(ln))
        cur = blocks[-1] if blocks else None
        if kind == "size":
            if cur is not None and cur.kind == "heading" and _continues_heading(cur.lines[-1], ln):
                cur.lines.append(ln)  # a heading wrapped onto two lines
            else:
                blocks.append(_Block("heading", [ln], page))
            continue
        prev = lines[i - 1] if i else None
        boundary = (
            cur is None
            or prev is None
            or cur.kind == "heading"
            or weak(ln) != weak(prev)
            or _starts_paragraph(prev, ln, right_edge, pitch)
        )
        if boundary:
            blocks.append(_Block("para", [ln], page))
        else:
            assert cur is not None  # noqa: S101 - boundary covers cur is None
            cur.lines.append(ln)
    for b in blocks:
        if b.kind == "para" and all(weak(ln) for ln in b.lines) and len(b.text) <= 120:
            b.kind = "heading"
    return blocks


def _numbering_depth(title: str) -> int | None:
    """1 for "3", "3." or "Appendix A"; 2 for "3.2"; None when unnumbered."""
    m = _NUMBERING.match(title)
    if m is None:
        return None
    return m.group(1).count(".") + 1 if m.group(1) else 1


def _section_number(title: str) -> str | None:
    """The section number ("3.2" for "3.2 Methods"), or None ("Appendix A", unnumbered)."""
    m = _NUMBERING.match(title)
    return m.group(1) if m and m.group(1) else None


def _assign_levels(blocks: list[_Block], body: float) -> None:
    """Heading levels: by size first, then by section numbering.

    Headings set larger than the body text get levels 1-3 by size (sizes within 8% count as
    one). Body-size headings (bold or capitalised) come below those: a numbered one sits one
    level under the heading with its parent number ("3.2.1" under "3.2", "1.1" under a larger
    "1. Introduction"), or nests by its numbering when there is none; an unnumbered one sits
    one level under the last numbered or larger heading. Finally no heading is more than one
    level below the one before it, so the outline has no gaps.
    """
    headings = [b for b in blocks if b.kind == "heading"]
    big = sorted({b.lines[0].size for b in headings if b.lines[0].size >= body * 1.18})[::-1]
    level: dict[float, int] = {}
    anchor: float | None = None
    rank = 0
    for size in big:
        if anchor is None or anchor - size > 0.08 * anchor:
            rank += 1
            anchor = size
        level[size] = min(3, rank)
    base = min(3, rank) + 1
    by_number: dict[str, int] = {}
    parent_level: int | None = None  # the last numbered or larger heading
    for b in headings:
        number = _section_number(b.text)
        if b.lines[0].size in level:
            b.level = level[b.lines[0].size]
        elif number is not None:
            parent = number.rpartition(".")[0]
            b.level = by_number[parent] + 1 if parent in by_number else base + number.count(".")
        elif _numbering_depth(b.text) is not None:  # "Appendix B", "Part 2"
            b.level = base
        else:
            b.level = parent_level + 1 if parent_level is not None else base
        b.level = min(6, b.level)
        if number is not None:
            by_number[number] = b.level
        if b.lines[0].size in level or _numbering_depth(b.text) is not None:
            parent_level = b.level
    previous = 0
    for b in headings:
        b.level = min(b.level, previous + 1)
        previous = b.level


def _run_in_labels(blocks: list[_Block], body: float) -> list[_Block]:
    """A body-size "heading" ending in a colon ("GOVERN 1:", "Note:") labels the text after it
    rather than titling a section, so it becomes the start of the next paragraph."""
    out: list[_Block] = []
    for b in blocks:
        prev = out[-1] if out else None
        if prev is not None and prev.kind == "label" and b.kind == "para" and b.page == prev.page:
            prev.lines.extend(b.lines)
            prev.kind = "para"
            continue
        if prev is not None and prev.kind == "label":
            prev.kind = "para"
        if b.kind == "heading" and b.text.endswith(":") and b.lines[0].size < body * 1.18:
            b.kind = "label"
        out.append(b)
    if out and out[-1].kind == "label":
        out[-1].kind = "para"
    return out


def _demote_cover(blocks: list[_Block], *, pages: int = 2) -> None:
    """Cover pages hold the title, report number and authors in large type. As headings they
    would head the path of every passage ("Title › Report no. › 3 Results"), so on the first
    pages, when they carry far less running text than a typical page of a longer document,
    they are kept as plain text instead."""
    text_chars: Counter[int] = Counter()
    for b in blocks:
        if b.kind == "para":
            text_chars[b.page] += len(b.text)
    last_page = max((b.page for b in blocks), default=0)
    if last_page < 5:
        return
    typical = sorted(text_chars[p] for p in range(1, last_page + 1))[last_page // 2]
    for b in blocks:
        if b.kind == "heading" and b.page <= pages and text_chars[b.page] < 0.25 * typical:
            b.kind = "para"


# --------------------------------------------------------------------------- build
def _is_contents_page(lines: list[_Line]) -> bool:
    """A table of contents: most lines end with a page number."""
    numbered = sum(1 for ln in lines if _TOC_ENTRY.search(ln.text))
    return numbered >= 5 and numbered >= 0.4 * len(lines)


def _heading_kinds(pages: list[list[_Line]], body: float) -> tuple[dict[int, HeadingKind], bool]:
    """Heading candidates by line id, and whether the weak signals (bold, capitals) count.

    Not headings: entries on a table-of-contents page (they would duplicate the real
    headings), and short bold or capitalised lines repeated three or more times (table
    column headers on every page of a table). If candidates make up more than
    ``MAX_HEADING_SHARE`` of the text (by characters, so a short memo with a title still has
    one), the weak signals are dropped; if size alone still marks that much, nothing is a
    heading (slides, forms).
    """
    kinds: dict[int, HeadingKind] = {}
    chars: dict[int, int] = {}
    weak_texts: Counter[str] = Counter()
    total = 0
    for lines in pages:
        contents = _is_contents_page(lines)
        for ln in lines:
            total += len(ln.text)
            k = _heading_kind(ln, body)
            if k is None or (contents and _TOC_ENTRY.search(ln.text)):
                continue
            kinds[id(ln)] = k
            chars[id(ln)] = len(ln.text)
            if k != "size":
                weak_texts[ln.text.lower()] += 1
    for lines in pages:
        for ln in lines:
            if kinds.get(id(ln)) in ("bold", "caps") and weak_texts[ln.text.lower()] >= 3:
                del kinds[id(ln)]

    def share(selected: dict[int, HeadingKind]) -> float:
        return sum(chars[i] for i in selected) / total if total else 0.0

    if share(kinds) <= MAX_HEADING_SHARE:
        return kinds, True
    kinds = {k: v for k, v in kinds.items() if v == "size"}
    if share(kinds) > MAX_HEADING_SHARE:
        kinds = {}
    return kinds, False


class _Writer:
    """Appends blocks to the text, recording where each page starts and the outline."""

    def __init__(self, pages: int, max_chars: int) -> None:
        self.parts: list[str] = []
        self.length = 0
        self.starts: list[int | None] = [None] * pages
        self.outline: list[OutlineEntry] = []
        self.truncated = False
        self.max_chars = max_chars
        self.open_para = False  # the last part is a paragraph that may continue
        self.keep_hyphen = False  # ... and its last line ends in a compound's hyphen

    def _continues(self, b: _Block, text: str) -> bool:
        if not (self.open_para and self.parts) or self.starts[b.page - 1] is not None:
            return False
        return not _ENDS_SENTENCE.search(self.parts[-1]) and text[:1].islower()

    def add(self, b: _Block) -> bool:
        """False once the text is full."""
        text = b.text
        if b.kind == "para" and self._continues(b, text):
            # The paragraph runs on from the previous page.
            prev = self.parts[-1]
            if self.length + 1 + len(text) > self.max_chars:
                self.truncated = True
                return False
            if _broken_word(prev, text) and not self.keep_hyphen:
                self.parts[-1], self.length, joiner = prev[:-1], self.length - 1, ""
            else:
                joiner = "" if _broken_word(prev, text) else " "
            self.starts[b.page - 1] = self.length + len(joiner)
            self.parts[-1] += joiner + text
            self.length += len(joiner) + len(text)
            self.keep_hyphen = b.lines[-1].keep_hyphen
            return True
        if b.kind == "heading":
            title = text[:200]
            chunk = f"{'#' * b.level} {title}"
        else:
            chunk = f" {text}" if text.startswith("#") else text  # never a Markdown heading
        sep = 2 if self.parts else 0
        if self.length + sep + len(chunk) > self.max_chars:
            self.truncated = True
            return False
        if self.starts[b.page - 1] is None:
            self.starts[b.page - 1] = self.length + sep
        if b.kind == "heading":
            self.outline.append(OutlineEntry(b.level, title, b.page))
        self.parts.append(chunk)
        self.length += sep + len(chunk)
        self.open_para = b.kind == "para"
        self.keep_hyphen = b.lines[-1].keep_hyphen
        return True

    def result(self) -> BuiltDocument:
        text = "\n\n".join(self.parts)
        filled: list[int] = []
        nxt = len(text)
        for s in reversed(self.starts):
            nxt = s if s is not None else nxt
            filled.append(min(nxt, len(text)))
        filled.reverse()
        for i in range(1, len(filled)):  # non-decreasing even if a page had no content
            filled[i] = max(filled[i], filled[i - 1])
        return BuiltDocument(text, filled, self.outline, self.truncated)


def build_document(raw_pages: list[RawPage], *, max_chars: int = 300_000) -> BuiltDocument:
    pages = [
        [
            _Line(clean_text(r.text), r.top, r.bottom, r.x0, r.x1, r.size, r.bold)
            for r in p.lines
            if clean_text(r.text)
        ]
        for p in raw_pages
    ]
    pages = _strip_running(pages, [p.height for p in raw_pages], _body_size(pages))
    _mark_compound_hyphens(pages)
    body = _body_size(pages)
    kinds, use_weak = _heading_kinds(pages, body)
    blocks: list[_Block] = []
    for number, lines in enumerate(pages, start=1):
        blocks.extend(_page_blocks(lines, number, body, kinds, use_weak))
    _demote_cover(blocks)
    blocks = _run_in_labels(blocks, body)
    _assign_levels(blocks, body)
    writer = _Writer(len(raw_pages), max_chars)
    for b in blocks:
        if not writer.add(b):
            break
    return writer.result()
