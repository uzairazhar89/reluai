"""Section-aware chunking where every chunk is an exact span of the source text.

Markdown headings (``#`` to ``######``) start sections; each chunk records the heading path
it sits under ("Refunds › Damaged items") and its character offsets, so
``source[chunk.start:chunk.end] == chunk.text`` always holds and a citation can point at
the precise passage. Within a section, sentences are packed up to a word budget; a sentence
longer than the budget is split on word boundaries. Consecutive chunks of a section can
share ``overlap`` sentences so an answer spanning a boundary is still found whole.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t#]*$", re.MULTILINE)
# A sentence ends at . ! ? followed by whitespace, or at a blank line / list item break.
_SENTENCE = re.compile(r"\S.*?(?:[.!?](?=\s)|(?=\n\s*\n)|(?=\n\s*[-*•]\s)|$)", re.DOTALL)
_WORD = re.compile(r"\S+")
HEADING_SEPARATOR = " › "


@dataclass(frozen=True, slots=True)
class Chunk:
    ordinal: int
    heading: str  # "Refunds › Damaged items"; empty before the first heading
    text: str
    start: int
    end: int

    @property
    def words(self) -> int:
        return len(_WORD.findall(self.text))


@dataclass(frozen=True, slots=True)
class _Section:
    heading: str
    start: int
    end: int


def _sections(source: str) -> list[_Section]:
    sections: list[_Section] = []
    path: list[tuple[int, str]] = []
    heading = ""
    cursor = 0
    for m in _HEADING.finditer(source):
        if source[cursor : m.start()].strip():
            sections.append(_Section(heading, cursor, m.start()))
        level = len(m.group(1))
        path = [(lvl, title) for lvl, title in path if lvl < level]
        path.append((level, m.group(2).strip()))
        heading = HEADING_SEPARATOR.join(title for _, title in path)
        cursor = m.end()
    if source[cursor:].strip():
        sections.append(_Section(heading, cursor, len(source)))
    return sections


def _units(source: str, section: _Section, max_words: int) -> list[tuple[int, int]]:
    """Sentence spans in a section; over-long sentences become word windows."""
    units: list[tuple[int, int]] = []
    body = source[section.start : section.end]
    for m in _SENTENCE.finditer(body):
        start, end = section.start + m.start(), section.start + m.end()
        text = source[start:end].rstrip()
        end = start + len(text)
        if not text:
            continue
        words = list(_WORD.finditer(text))
        if len(words) <= max_words:
            units.append((start, end))
            continue
        for i in range(0, len(words), max_words):
            window = words[i : i + max_words]
            units.append((start + window[0].start(), start + window[-1].end()))
    return units


def chunk_text(source: str, *, max_words: int = 160, overlap: int = 1) -> list[Chunk]:
    """Split ``source`` into chunks of at most about ``max_words`` words."""
    if max_words < 10:
        raise ValueError("max_words must be at least 10")
    if overlap < 0:
        raise ValueError("overlap cannot be negative")
    chunks: list[Chunk] = []
    for section in _sections(source):
        units = _units(source, section, max_words)
        counts = [len(_WORD.findall(source[s:e])) for s, e in units]
        i = 0
        while i < len(units):
            j, words = i, 0
            while j < len(units) and (j == i or words + counts[j] <= max_words):
                words += counts[j]
                j += 1
            start, end = units[i][0], units[j - 1][1]
            chunks.append(Chunk(len(chunks), section.heading, source[start:end], start, end))
            if j >= len(units):
                break
            i = max(i + 1, j - overlap)  # always advance, repeat up to `overlap` sentences
    return chunks
