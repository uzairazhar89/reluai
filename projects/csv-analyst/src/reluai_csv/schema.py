"""What the analyst knows about a table: columns, their kinds, and the words that refer to them.

The same description drives the deterministic parser, the plan validator, the SQL compiler
and the prompt sent to an LLM, so all four agree on which columns exist.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

ColumnKind = Literal["integer", "number", "text", "date", "boolean", "other"]
NUMERIC_KINDS: frozenset[str] = frozenset({"integer", "number"})
ORDERED_KINDS: frozenset[str] = frozenset({"integer", "number", "date"})


@dataclass(frozen=True, slots=True)
class ColumnInfo:
    name: str
    kind: ColumnKind
    sql_type: str
    description: str = ""
    synonyms: tuple[str, ...] = ()
    """Words or phrases that refer to this column ("price", "unit price")."""
    entity: str | None = None
    """Plural noun counted with COUNT(DISTINCT ...): "customers" for ``customer_id``."""
    values: tuple[str, ...] = ()
    """Known values of a low-cardinality text column, used to recognise filters."""
    value_aliases: tuple[tuple[str, str], ...] = ()
    """Other spellings of known values: ("uk", "United Kingdom")."""
    distinct: int | None = None
    additive: bool = True
    """Whether totals make sense ("revenue") or averages do ("unit price")."""
    title: str | None = None
    """Display name in summaries ("product" for ``description``)."""

    @property
    def numeric(self) -> bool:
        return self.kind in NUMERIC_KINDS

    @property
    def label(self) -> str:
        return self.title or self.name.replace("_", " ")


@dataclass(frozen=True, slots=True)
class DatasetSchema:
    table: str
    columns: tuple[ColumnInfo, ...]
    row_noun: str = "rows"
    default_date: str | None = None
    """Column used for "per month", "over time" and year filters."""
    default_measure: str | None = None
    """Numeric column meant by "sales" or "total" when no column is named."""
    _index: dict[str, ColumnInfo] = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self) -> None:
        for c in self.columns:
            self._index[c.name.lower()] = c

    def column(self, name: str) -> ColumnInfo | None:
        return self._index.get(name.lower())

    @property
    def names(self) -> list[str]:
        return [c.name for c in self.columns]

    def date_columns(self) -> list[ColumnInfo]:
        return [c for c in self.columns if c.kind == "date"]


_KIND_PATTERNS: tuple[tuple[str, ColumnKind], ...] = (
    (r"^(TINYINT|SMALLINT|INTEGER|BIGINT|HUGEINT|UTINYINT|USMALLINT|UINTEGER|UBIGINT)$", "integer"),
    (r"^(FLOAT|DOUBLE|REAL|DECIMAL.*)$", "number"),
    (r"^(VARCHAR|TEXT|STRING).*$", "text"),
    (r"^(DATE|TIMESTAMP.*)$", "date"),
    (r"^BOOLEAN$", "boolean"),
)


def kind_from_sql_type(sql_type: str) -> ColumnKind:
    upper = sql_type.strip().upper()
    for pattern, kind in _KIND_PATTERNS:
        if re.match(pattern, upper):
            return kind
    return "other"
