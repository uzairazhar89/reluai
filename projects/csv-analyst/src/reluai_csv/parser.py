"""Deterministic intent parser: plain-English questions to query plans, without any model.

It recognises a fixed set of question shapes (counts, totals and averages, breakdowns by a
column, top/bottom N, time series, most common values, comparisons) combined with filters
(category values, years and months, numeric thresholds, missing values, true/false columns).

Every word has to be accounted for: a column or its synonym, a known value, a number, a
keyword, or a filler word. If anything is left over, the parser declines instead of
guessing, and the question goes to the LLM fallback (or back to the visitor).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from reluai_csv.plan import Filter, Grain, Metric, QueryPlan, Scalar, Sort, TimeBucket
from reluai_csv.schema import ColumnInfo, DatasetSchema

# ------------------------------------------------------------------------- vocabulary
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "in",
        "on",
        "at",
        "for",
        "to",
        "from",
        "with",
        "and",
        "or",
        "by",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "do",
        "does",
        "did",
        "have",
        "has",
        "had",
        "there",
        "their",
        "them",
        "they",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "what",
        "which",
        "who",
        "whats",
        "show",
        "me",
        "list",
        "give",
        "tell",
        "find",
        "get",
        "display",
        "please",
        "i",
        "we",
        "our",
        "my",
        "you",
        "your",
        "how",
        "much",
        "can",
        "could",
        "would",
        "will",
        "should",
        "s",
        "all",
        "value",
        "values",
        "amount",
        "figure",
        "figures",
        "number",
        "numbers",
        "each",
        "every",
        "per",
        "as",
        "overall",
        "altogether",
        "into",
        "within",
        "made",
        "make",
        "generated",
        "earned",
        "sold",
        "bought",
        "purchased",
        "placed",
        "recorded",
        "happened",
        "came",
        "come",
        "see",
        "just",
        "only",
        "data",
        "table",
        "dataset",
        "where",
        "whose",
        "had",
        "got",
        "rows?",
        "lines?",
        "across",
        "so",
        "far",
        "ever",
        "any",
        "some",
    ]
)
# "rows?" / "lines?" above are deliberately not real words; row nouns are handled separately.

FILLER_VERBS = frozenset({"generated", "made", "earned", "sold", "bought", "purchased", "placed"})
ROW_NOUNS = frozenset(
    {
        "row",
        "rows",
        "record",
        "records",
        "line",
        "lines",
        "entries",
        "entry",
        "invoice line",
        "invoice lines",
    }
)
NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20, "fifty": 50,
}  # fmt: skip
MONTHS = {
    m: i + 1
    for i, names in enumerate(
        [
            ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"),
            ("may",), ("june", "jun"), ("july", "jul"), ("august", "aug"),
            ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"),
            ("december", "dec"),
        ]
    )
    for m in names
}  # fmt: skip
GRAINS: dict[str, Grain] = {
    "day": "day", "days": "day", "daily": "day", "date": "day",
    "week": "week", "weeks": "week", "weekly": "week",
    "month": "month", "months": "month", "monthly": "month",
    "quarter": "quarter", "quarters": "quarter", "quarterly": "quarter",
    "year": "year", "years": "year", "yearly": "year", "annual": "year", "annually": "year",
}  # fmt: skip
GRAIN_ADJECTIVES = frozenset({"daily", "weekly", "monthly", "quarterly", "yearly", "annual"})

# Multi-word keyword phrases first (longest match wins).
KEYWORDS: dict[tuple[str, ...], tuple[str, str]] = {
    ("how", "many"): ("agg", "count"),
    ("number", "of"): ("agg", "count"),
    ("count", "of"): ("agg", "count"),
    ("count",): ("agg", "count"),
    ("total",): ("agg", "sum"),
    ("sum", "of"): ("agg", "sum"),
    ("sum",): ("agg", "sum"),
    ("average",): ("agg", "avg"),
    ("mean",): ("agg", "avg"),
    ("avg",): ("agg", "avg"),
    ("typical",): ("agg", "avg"),
    ("maximum",): ("agg", "max"),
    ("max",): ("agg", "max"),
    ("minimum",): ("agg", "min"),
    ("min",): ("agg", "min"),
    ("most", "expensive"): ("extreme", "max_price"),
    ("cheapest",): ("extreme", "min_price"),
    ("highest",): ("rank", "desc"),
    ("largest",): ("rank", "desc"),
    ("biggest",): ("rank", "desc"),
    ("greatest",): ("rank", "desc"),
    ("most",): ("rank", "desc"),
    ("top",): ("rank", "desc"),
    ("best",): ("rank", "desc"),
    ("lowest",): ("rank", "asc"),
    ("smallest",): ("rank", "asc"),
    ("least",): ("rank", "asc"),
    ("fewest",): ("rank", "asc"),
    ("bottom",): ("rank", "asc"),
    ("worst",): ("rank", "asc"),
    ("best", "selling"): ("bestselling", ""),
    ("top", "selling"): ("bestselling", ""),
    ("least", "common"): ("common", "asc"),
    ("least", "popular"): ("common", "asc"),
    ("least", "frequent"): ("common", "asc"),
    ("rarest",): ("common", "asc"),
    ("earliest",): ("agg", "min"),
    ("first",): ("agg", "min"),
    ("latest",): ("agg", "max"),
    ("last",): ("agg", "max"),
    ("most", "recent"): ("agg", "max"),
    ("most", "common"): ("common", ""),
    ("most", "frequent"): ("common", ""),
    ("most", "popular"): ("common", ""),
    ("breakdown", "of"): ("common", ""),
    ("distribution", "of"): ("common", ""),
    ("frequency", "of"): ("common", ""),
    ("distinct",): ("distinct", ""),
    ("unique",): ("distinct", ""),
    ("different",): ("distinct", ""),
    ("broken", "down", "by"): ("group", ""),
    ("split", "by"): ("group", ""),
    ("grouped", "by"): ("group", ""),
    ("for", "each"): ("group", ""),
    ("for", "every"): ("group", ""),
    ("by",): ("group", ""),
    ("per",): ("group", ""),
    ("each",): ("group", ""),
    ("every",): ("group", ""),
    ("over", "time"): ("trend", ""),
    ("trend",): ("trend", ""),
    ("trends",): ("trend", ""),
    ("time", "series"): ("trend", ""),
    ("more", "than"): ("cmp", "gt"),
    ("greater", "than"): ("cmp", "gt"),
    ("higher", "than"): ("cmp", "gt"),
    ("over",): ("cmp", "gt"),
    ("above",): ("cmp", "gt"),
    ("exceeding",): ("cmp", "gt"),
    ("at", "least"): ("cmp", "gte"),
    ("less", "than"): ("cmp", "lt"),
    ("fewer", "than"): ("cmp", "lt"),
    ("lower", "than"): ("cmp", "lt"),
    ("under",): ("cmp", "lt"),
    ("below",): ("cmp", "lt"),
    ("at", "most"): ("cmp", "lte"),
    ("or", "more"): ("postcmp", "gte"),
    ("or", "less"): ("postcmp", "lte"),
    ("or", "fewer"): ("postcmp", "lte"),
    (">=",): ("cmp", "gte"),
    ("<=",): ("cmp", "lte"),
    (">",): ("cmp", "gt"),
    ("<",): ("cmp", "lt"),
    ("=",): ("cmp", "eq"),
    ("equal", "to"): ("cmp", "eq"),
    ("excluding",): ("exclude", ""),
    ("exclude",): ("exclude", ""),
    ("except", "for"): ("exclude", ""),
    ("except",): ("exclude", ""),
    ("other", "than"): ("exclude", ""),
    ("apart", "from"): ("exclude", ""),
    ("outside",): ("exclude", ""),
    ("not", "in"): ("exclude", ""),
    ("not",): ("exclude", ""),
    ("non",): ("exclude", ""),
    ("without",): ("missing", ""),
    ("with", "no"): ("missing", ""),
    ("missing",): ("missing", ""),
    ("no",): ("missing", ""),
    ("blank",): ("missing", ""),
    ("empty",): ("missing", ""),
    ("between",): ("dateprep", "between"),
    ("during",): ("dateprep", "in"),
    ("before",): ("dateprep", "before"),
    ("until",): ("dateprep", "until"),
    ("up", "to"): ("dateprep", "until"),
    ("after",): ("dateprep", "after"),
    ("since",): ("dateprep", "since"),
    ("compare",): ("compare", ""),
    ("comparing",): ("compare", ""),
    ("vs",): ("compare", ""),
    ("versus",): ("compare", ""),
    ("containing",): ("contains", ""),
    ("contains",): ("contains", ""),
    ("contain",): ("contains", ""),
    ("named",): ("contains", ""),
    ("called",): ("contains", ""),
    ("all",): ("all", ""),
    ("and",): ("and", ""),
    ("in",): ("in", ""),
    ("for",): ("in", ""),
    ("from",): ("in", ""),
    ("of",): ("of", ""),
}

_TOKEN_RE = re.compile(r'"[^"]{1,60}"|\'[^\']{1,60}\'|\d+(?:,\d{3})*(?:\.\d+)?|>=|<=|[<>=]|[a-z]+')


@dataclass(slots=True)
class Tok:
    kind: str  # col | value | kw:<type> | num | year | month | quoted | row | grain | word
    text: str
    col: ColumnInfo | None = None
    value: str | None = None
    arg: str = ""
    number: float | None = None
    plural: bool = False
    used: bool = False
    subject: bool = False  # the thing a filter describes ("lines with quantity over 10")


@dataclass(slots=True)
class Parsed:
    plan: QueryPlan | None
    pattern: str | None = None
    reason: str | None = None
    unknown: list[str] = field(default_factory=list)


def groupable(col: ColumnInfo | None) -> bool:
    """Columns that make sense as groups: categories and identifiers, not measures or dates."""
    if col is None or col.kind in {"date", "boolean", "other"}:
        return False
    return not col.numeric or col.entity is not None


def _singular(word: str) -> str:
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def _normalise(question: str) -> str:
    q = question.lower().replace("’", "'").replace("“", '"').replace("”", '"')
    q = re.sub(r"\bwhat's\b", "what is", q)
    q = re.sub(r"(\w)'s\b", r"\1", q)
    q = q.replace("best-selling", "best selling").replace("top-selling", "top selling")
    q = q.replace("£", " ").replace("$", " ").replace("€", " ")
    return q


class _Lexicon:
    def __init__(self, schema: DatasetSchema) -> None:
        self.phrases: dict[tuple[str, ...], Tok] = {}
        for col in schema.columns:
            names = {col.name.lower(), col.label.lower(), *(s.lower() for s in col.synonyms)}
            for name in names:
                self._add(name, Tok("col", name, col=col))
                self._add(_plural(name), Tok("col", name, col=col, plural=True))
            if col.entity:
                self._add(col.entity, Tok("col", col.entity, col=col, plural=True))
                self._add(_singular_phrase(col.entity), Tok("col", col.entity, col=col))
            for value in col.values:
                if 0 < len(value.split()) <= 4:
                    self._add(value.lower(), Tok("value", value, col=col, value=value))
            for alias, canonical in col.value_aliases:
                if canonical in col.values:
                    self._add(alias, Tok("value", alias, col=col, value=canonical))
        for words, (kind, arg) in KEYWORDS.items():
            self.phrases.setdefault(words, Tok(f"kw:{kind}", " ".join(words), arg=arg))
        for row in ROW_NOUNS:
            self.phrases.setdefault(tuple(row.split()), Tok("row", row))

    def _add(self, phrase: str, tok: Tok) -> None:
        words = tuple(_TOKEN_RE.findall(phrase))
        if words and words not in self.phrases:
            self.phrases[words] = tok


def _plural(name: str) -> str:
    last = name.rsplit(maxsplit=1)[-1] if name.split() else name
    if last.endswith("s"):
        return name
    plural_last = last[:-1] + "ies" if last.endswith("y") else last + "s"
    return name[: len(name) - len(last)] + plural_last


def _singular_phrase(name: str) -> str:
    parts = name.split()
    return " ".join([*parts[:-1], _singular(parts[-1])]) if parts else name


def _lex(question: str, lexicon: _Lexicon) -> list[Tok]:
    words = _TOKEN_RE.findall(_normalise(question))
    toks: list[Tok] = []
    i = 0
    while i < len(words):
        w = words[i]
        if w[0] in "\"'":
            toks.append(Tok("quoted", w[1:-1].strip()))
            i += 1
            continue
        if w[0].isdigit():
            n = float(w.replace(",", ""))
            if re.fullmatch(r"(19|20)\d\d", w):
                toks.append(Tok("year", w, number=n))
            else:
                toks.append(Tok("num", w, number=n))
            i += 1
            continue
        for size in (4, 3, 2, 1):
            key = tuple(words[i : i + size])
            if len(key) == size and key in lexicon.phrases:
                proto = lexicon.phrases[key]
                toks.append(
                    Tok(
                        proto.kind,
                        " ".join(key),
                        col=proto.col,
                        value=proto.value,
                        arg=proto.arg,
                        plural=proto.plural,
                    )
                )
                i += size
                break
        else:
            if w in MONTHS:
                toks.append(Tok("month", w, number=MONTHS[w]))
            elif w in GRAINS:
                toks.append(Tok("grain", w, arg=GRAINS[w]))
            elif w in NUMBER_WORDS:
                toks.append(Tok("num", w, number=NUMBER_WORDS[w]))
            else:
                toks.append(Tok("word", w))
            i += 1
    return toks


# ------------------------------------------------------------------------- assembly
class _Builder:
    def __init__(self, toks: list[Tok], schema: DatasetSchema) -> None:
        self.t = toks
        self.schema = schema
        self.metrics: list[Metric] = []
        self.groups: list[str] = []
        self.bucket: TimeBucket | None = None
        self.filters: list[Filter] = []
        self.sort: Sort | None = None
        self.limit: int | None = None
        self.pattern = "aggregate"
        self.fail: str | None = None
        self.which = False
        self.which_plural = False

    # --------------------------------------------------------------- helpers
    def at(self, i: int) -> Tok | None:
        return self.t[i] if 0 <= i < len(self.t) else None

    def next_kind(self, i: int, *kinds: str, skip: frozenset[str] = frozenset()) -> int | None:
        j = i + 1
        while j < len(self.t):
            tok = self.t[j]
            if tok.kind in kinds and not tok.used:
                return j
            if tok.kind == "word" and tok.text in STOPWORDS | skip:
                j += 1
                continue
            if tok.kind in {"kw:of", "kw:in", "kw:and"} and "kw:connector" in skip:
                j += 1
                continue
            return None
        return None

    def date_col(self) -> ColumnInfo | None:
        name = self.schema.default_date
        return self.schema.column(name) if name else None

    # --------------------------------------------------------------- passes
    def run(self) -> None:
        for step in (self.filters_pass, self.grouping_pass, self.metric_pass):
            step()
            if self.fail:
                return
        if len(self.groups) + (1 if self.bucket else 0) > 2:
            self.fail = "more than two groupings (including time)"

    def filters_pass(self) -> None:  # noqa: PLR0912, PLR0915
        t = self.t
        values: dict[str, list[tuple[str, bool]]] = {}
        last_negated: dict[str, bool] = {}
        for i, tok in enumerate(t):
            if tok.kind == "value" and tok.col is not None and tok.value is not None:
                negated = any(
                    p is not None and p.kind == "kw:exclude"
                    for p in (self.at(i - 1), self.at(i - 2))
                )
                prev, prev2 = self.at(i - 1), self.at(i - 2)
                if (
                    prev is not None
                    and prev.kind in {"kw:and", "kw:or"}
                    and prev2 is not None
                    and prev2.kind == "value"
                    and prev2.col is tok.col
                ):
                    negated = negated or last_negated.get(tok.col.name, False)
                    prev.used = True
                last_negated[tok.col.name] = negated
                tok.used = True
                for p in (self.at(i - 1), self.at(i - 2)):
                    if p is not None and p.kind in {"kw:exclude", "kw:in"}:
                        p.used = True
                values.setdefault(tok.col.name, []).append((tok.value, negated))
        for col_name, items in values.items():
            pos = [v for v, neg in items if not neg]
            neg = [v for v, n in items if n]
            if len(pos) == 1:
                self.filters.append(Filter(column=col_name, op="eq", value=pos[0]))
            elif pos:
                self.filters.append(Filter(column=col_name, op="in", value=list(pos)))
            if len(neg) == 1:
                self.filters.append(Filter(column=col_name, op="ne", value=neg[0]))
            elif neg:
                self.filters.append(Filter(column=col_name, op="not_in", value=list(neg)))

        # Dates: [prep] [month] year, "between Y and Y"
        i = 0
        while i < len(t):
            tok = t[i]
            if tok.kind in {"year", "month"} and not tok.used:
                self.date_filter(i)
                if self.fail:
                    return
            i += 1

        # Numeric thresholds: <col> <cmp> <num>, <num> or more
        for i, tok in enumerate(t):
            if tok.kind == "kw:cmp" and not tok.used:
                j = self.next_kind(i, "num", "year")
                if j is None:
                    continue
                col = self.threshold_column(i)
                if col is None:
                    self.fail = "a comparison without a numeric column"
                    return
                tok.used = t[j].used = True
                self.mark_subject(i, col)
                self.filters.append(Filter(column=col.name, op=tok.arg, value=_num(t[j])))  # type: ignore[arg-type]
            if tok.kind == "kw:postcmp" and not tok.used:
                prev = self.at(i - 1)
                if prev is None or prev.kind != "num":
                    continue
                col = self.threshold_column(i - 1)
                if col is None:
                    self.fail = "a comparison without a numeric column"
                    return
                tok.used = prev.used = True
                self.mark_subject(i - 1, col)
                self.filters.append(Filter(column=col.name, op=tok.arg, value=_num(prev)))  # type: ignore[arg-type]

        # Equality with a number: "unit price of 0", "quantity is 12"
        for i, tok in enumerate(t):
            if tok.kind != "num" or tok.used:
                continue
            prev = self.at(i - 1)
            if prev is None or not (
                prev.kind == "kw:of" or (prev.kind == "word" and prev.text in {"is", "was"})
            ):
                continue
            col = self.threshold_column(i - 1)
            if col is None:
                continue
            tok.used = prev.used = True
            self.mark_subject(i - 1, col)
            self.filters.append(Filter(column=col.name, op="eq", value=_num(tok)))

        # Missing values: "missing customer id", "without a customer id", "customer id missing"
        for i, tok in enumerate(t):
            if tok.kind != "kw:missing" or tok.used:
                continue
            j = self.next_kind(i, "col")
            if j is not None and t[j].col is not None and t[j].col.kind != "boolean":  # type: ignore[union-attr]
                col = t[j].col
                assert col is not None  # noqa: S101
                tok.used = t[j].used = True
                self.filters.append(Filter(column=col.name, op="is_null"))
                continue
            prev = self.at(i - 1)
            if prev is not None and prev.kind == "col" and prev.col and not prev.col.numeric:
                tok.used = prev.used = True
                self.filters.append(Filter(column=prev.col.name, op="is_null"))

        # True/false columns: "cancelled invoices", "excluding cancellations"
        for i, tok in enumerate(t):
            if tok.kind == "col" and tok.col is not None and tok.col.kind == "boolean":
                negated = False
                for p in (self.at(i - 1), self.at(i - 2)):
                    if p is not None and p.kind in {"kw:exclude", "kw:missing"} and not p.used:
                        negated = True
                        p.used = True
                        break
                tok.used = True
                self.filters.append(Filter(column=tok.col.name, op="eq", value=not negated))

        # Quoted text: products containing "heart"
        for i, tok in enumerate(t):
            if tok.kind != "quoted":
                continue
            target = None
            for j in range(i - 1, max(-1, i - 5), -1):
                prev = t[j]
                if prev.kind == "col" and prev.col is not None and prev.col.kind == "text":
                    target = prev.col
                    prev.subject = True
                    break
            if target is None or not tok.text:
                self.fail = "quoted text without a text column to search"
                return
            tok.used = True
            for j in range(max(0, i - 3), i):
                if t[j].kind == "kw:contains":
                    t[j].used = True
            self.filters.append(Filter(column=target.name, op="contains", value=tok.text))

    def number_before(self, i: int) -> int | None:
        prev = self.at(i - 1)
        if prev is not None and prev.kind == "num" and not prev.used:
            prev.used = True
            return int(prev.number or 0)
        return None

    def mark_subject(self, i: int, col: ColumnInfo) -> None:
        for p in range(i - 1, max(-1, i - 4), -1):
            prev = self.t[p]
            if prev.kind == "col" and prev.col is col:
                prev.used = True
                return

    def threshold_column(self, i: int) -> ColumnInfo | None:
        for p in range(i - 1, max(-1, i - 4), -1):
            prev = self.t[p]
            if prev.kind == "col" and prev.col is not None and prev.col.numeric:
                return prev.col
        return None

    def date_filter(self, i: int) -> None:  # noqa: PLR0912
        t = self.t
        col = self.date_col()
        if col is None:
            self.fail = "a date filter, but the table has no date column"
            return
        start_i = i
        month = None
        if t[i].kind == "month":
            month = int(t[i].number or 0)
            if i + 1 < len(t) and t[i + 1].kind == "year":
                i += 1
            else:
                self.fail = "a month without a year"
                return
        year = int(t[i].number or 0)
        t[start_i].used = t[i].used = True
        period = f"{year:04d}-{month:02d}" if month else f"{year:04d}"
        prep = self.at(start_i - 1)
        op = "eq"
        if prep is not None and prep.kind == "kw:dateprep":
            prep.used = True
            op = {
                "in": "eq", "before": "lt", "until": "lte", "after": "gt", "since": "gte",
                "between": "between",
            }[prep.arg]  # fmt: skip
        elif prep is not None and prep.kind in {"kw:in", "kw:of"}:
            prep.used = True
        if op == "between":
            j = self.next_kind(i, "year", "month", skip=frozenset({"kw:connector"}))
            k = i + 1
            while k < len(t) and t[k].kind in {"kw:and"}:
                t[k].used = True
                k += 1
            if j is None:
                self.fail = "'between' needs two dates"
                return
            end_month = None
            if t[j].kind == "month":
                end_month = int(t[j].number or 0)
                if j + 1 < len(t) and t[j + 1].kind == "year":
                    t[j].used = True
                    j += 1
            t[j].used = True
            end_year = int(t[j].number or 0)
            end = f"{end_year:04d}-{end_month:02d}" if end_month else f"{end_year:04d}"
            self.filters.append(Filter(column=col.name, op="between", value=[period, end]))
            return
        if op == "eq":
            self.filters.append(Filter(column=col.name, op="eq", value=period))
        else:
            self.filters.append(Filter(column=col.name, op=op, value=period))  # type: ignore[arg-type]

    def grouping_pass(self) -> None:  # noqa: PLR0912, PLR0915
        t = self.t
        # "most common X" / "distribution of X"
        for i, tok in enumerate(t):
            if tok.kind == "kw:common" and not tok.used:
                j = self.next_kind(i, "col")
                if j is None:
                    self.fail = "'most common' without a column"
                    return
                col = t[j].col
                assert col is not None  # noqa: S101
                tok.used = t[j].used = True
                if col.kind == "date":
                    self.fail = "'most common' on a date"
                    return
                self.add_group(col)
                self.metrics.append(Metric(agg="count"))
                self.sort = "metric_asc" if tok.arg == "asc" else "metric_desc"
                self.limit = self.number_before(i) or 10
                self.pattern = "most_common"

        # "compare Germany and France" → group by the compared column
        for tok in t:
            if tok.kind == "kw:compare" and not tok.used:
                tok.used = True
                compared = [f for f in self.filters if f.op == "in"]
                if not compared:
                    self.fail = "'compare' without two or more values"
                    return
                col = self.schema.column(compared[0].column)
                assert col is not None  # noqa: S101
                self.add_group(col)
                self.pattern = "compare"

        # "most expensive product" / "cheapest products"
        for i, tok in enumerate(t):
            if tok.kind != "kw:extreme" or tok.used:
                continue
            price = next((c for c in self.schema.columns if c.numeric and not c.additive), None)
            if price is None:
                self.fail = "no price-like column"
                return
            tok.used = True
            j = self.next_kind(i, "col")
            direction: Sort = "metric_desc" if tok.arg == "max_price" else "metric_asc"
            if j is not None and groupable(t[j].col):
                col = t[j].col
                assert col is not None  # noqa: S101
                t[j].used = True
                self.add_group(col)
                self.metrics.append(Metric(agg="avg", column=price.name))
                n_before = self.number_before(i)
                self.sort, self.limit = direction, n_before or (10 if t[j].plural else 1)
                self.pattern = "top_n"
            else:
                if j is not None and t[j].col is price:
                    t[j].used = True
                agg = "max" if tok.arg == "max_price" else "min"
                self.metrics.append(Metric(agg=agg, column=price.name))  # type: ignore[arg-type]

        # "which country ..." / "what product ..." → the thing being asked about
        for i, tok in enumerate(t):
            if tok.kind == "grain" and not tok.used:
                prev = self.at(i - 1)
                if prev is not None and prev.kind == "word" and prev.text in {"which", "what"}:
                    tok.used = True
                    self.set_bucket(tok.arg)
                    self.which = True
                    self.pattern = "top_n"
                    continue
            if tok.kind != "col" or tok.used or not groupable(tok.col):
                continue
            prev = self.at(i - 1)
            if prev is not None and prev.kind == "word" and prev.text in {"which", "what"}:
                assert tok.col is not None  # noqa: S101
                tok.used = True
                self.add_group(tok.col)
                self.which = True
                self.which_plural = tok.plural
                if self.pattern == "aggregate":
                    self.pattern = "top_n"

        # top/bottom N <entity> [by <measure>]; "[top N] best selling X"
        for i, tok in enumerate(t):
            if tok.kind not in {"kw:rank", "kw:bestselling"} or tok.used:
                continue
            j = i + 1
            n = self.number_before(i)
            if j < len(t) and t[j].kind == "num":
                n = int(t[j].number or 0)
                t[j].used = True
                j += 1
            nxt = self.at(j)
            if tok.kind == "kw:rank" and nxt is not None and nxt.kind == "kw:bestselling":
                tok.used = True  # "top 20 best selling products"
                nxt.arg = str(n or "")
                continue
            if tok.kind == "kw:bestselling" and tok.arg:
                n = int(tok.arg)
            target = self.next_kind(j - 1, "col")
            if tok.kind == "kw:bestselling":
                if target is None:
                    self.fail = "'best selling' without a column"
                    return
                measure = self.schema.column("quantity") or self.measure_col()
                if measure is None:
                    self.fail = "no measure for 'best selling'"
                    return
                tok.used = t[target].used = True
                col = t[target].col
                assert col is not None  # noqa: S101
                self.add_group(col)
                self.metrics.append(Metric(agg="sum", column=measure.name))
                self.sort, self.limit = "metric_desc", n or 10
                self.pattern = "top_n"
                continue
            if target is None:
                if n is not None:
                    t[j - 1].used = False
                continue  # "highest price" etc. are decided in the metric pass
            col = t[target].col
            assert col is not None  # noqa: S101
            after = self.at(target + 1)
            if (
                col.numeric
                and not col.entity
                and after is not None
                and after.kind == "col"
                and not after.used
                and after.plural
                and groupable(after.col)
            ):
                # "lowest revenue countries": group the plural, rank by the measure
                tok.used = after.used = True
                assert after.col is not None  # noqa: S101
                self.add_group(after.col)
                self.sort = "metric_desc" if tok.arg == "desc" else "metric_asc"
                self.limit = n or 10
                self.pattern = "top_n"
                continue
            if (col.numeric and not col.entity) or self.which:
                if n is not None and self.at(j - 1) is not None and self.at(j - 1).kind == "num":  # type: ignore[union-attr]
                    t[j - 1].used = False
                continue  # "which country has the most customers": customers is the metric
            tok.used = t[target].used = True
            self.add_group(col)
            self.sort = "metric_desc" if tok.arg == "desc" else "metric_asc"
            self.limit = n or (10 if t[target].plural else 1)
            self.pattern = "top_n"

        # "by/per/for each X", grain words, "monthly", "over time"
        for i, tok in enumerate(t):
            if tok.kind == "kw:group" and not tok.used:
                if self.groups and self.metric_follows(i):
                    tok.used = True  # "top 5 countries by number of customers"
                    continue
                j = self.next_kind(i, "col", "grain", "row")
                if j is None:
                    continue
                nxt = t[j]
                if nxt.kind == "row":
                    tok.used = nxt.used = True  # "average revenue per invoice line"
                    continue
                self.second_group(j)
                if nxt.kind == "grain":
                    self.set_bucket(nxt.arg)
                    tok.used = nxt.used = True
                    continue
                col = nxt.col
                assert col is not None  # noqa: S101
                if col.kind == "date":
                    self.set_bucket("day")
                    tok.used = nxt.used = True
                    continue
                if col.numeric and not col.entity:
                    # "countries by revenue": the plural before "by" is the group
                    owner = self.unused_plural_before(i)
                    if owner is not None:
                        owner.used = tok.used = True
                        assert owner.col is not None  # noqa: S101
                        self.add_group(owner.col)
                        self.sort = self.sort or "metric_desc"
                        if self.pattern == "aggregate":
                            self.pattern = "top_n"
                    elif self.groups:
                        tok.used = True  # "top 10 products by revenue": the metric follows
                    continue
                if self.pattern == "top_n" and self.groups and self.metric_follows(i):
                    tok.used = True
                    continue
                tok.used = nxt.used = True
                self.add_group(col)
            elif tok.kind == "kw:all" and not tok.used:
                nxt_i = self.next_kind(i, "col")
                if nxt_i is not None:
                    cand = t[nxt_i]
                    if (
                        cand.plural
                        and groupable(cand.col)
                        and (self.measure_mentioned() or self.groups)
                    ):
                        assert cand.col is not None  # noqa: S101
                        tok.used = cand.used = True
                        self.add_group(cand.col)
                        self.limit = 100
            elif tok.kind == "grain" and not tok.used and tok.text in GRAIN_ADJECTIVES:
                self.set_bucket(tok.arg)
                tok.used = True
            elif tok.kind == "kw:trend" and not tok.used:
                self.set_bucket("month")
                tok.used = True

    def second_group(self, j: int) -> None:
        """'by month and country': the column after 'and' is a second grouping."""
        conj, other = self.at(j + 1), self.at(j + 2)
        if conj is None or other is None or conj.kind != "kw:and" or other.used:
            return
        if other.kind == "grain":
            conj.used = other.used = True
            self.set_bucket(other.arg)
        elif other.kind == "col" and groupable(other.col):
            assert other.col is not None  # noqa: S101
            conj.used = other.used = True
            self.add_group(other.col)

    def unused_plural_before(self, i: int) -> Tok | None:
        for p in range(i - 1, max(-1, i - 7), -1):
            prev = self.t[p]
            if prev.used or (prev.kind == "word" and prev.text in STOPWORDS):
                continue
            if prev.kind == "col" and not prev.used and prev.plural and groupable(prev.col):
                return prev
            if prev.kind not in {"word", "kw:all"}:
                return None
        return None

    def measure_mentioned(self) -> bool:
        return any(
            tok.kind == "col"
            and tok.col is not None
            and tok.col.numeric
            and tok.col.entity is None
            and not tok.used
            for tok in self.t
        )

    def add_group(self, col: ColumnInfo) -> None:
        if col.name not in self.groups:
            self.groups.append(col.name)

    def metric_follows(self, i: int) -> bool:
        nxt = self.at(i + 1)
        return nxt is not None and nxt.kind in {"kw:agg", "kw:rank"}

    def set_bucket(self, grain: str) -> None:
        col = self.date_col()
        if col is None:
            self.fail = "a time grouping, but the table has no date column"
            return
        self.bucket = TimeBucket(column=col.name, grain=grain)  # type: ignore[arg-type]
        if self.pattern not in {"top_n", "most_common", "compare"}:
            self.pattern = "time_series"

    def measure_col(self) -> ColumnInfo | None:
        name = self.schema.default_measure
        return self.schema.column(name) if name else None

    def next_unused_col(self, j: int) -> tuple[int, bool]:
        """Skip fillers, 'of', 'distinct' and tokens already used as filters."""
        distinct = False
        while j < len(self.t):
            tok = self.t[j]
            if tok.kind == "kw:distinct":
                distinct = True
                tok.used = True
            elif tok.kind == "kw:of":
                tok.used = True
            elif not (tok.kind == "word" and tok.text in STOPWORDS) and not (
                tok.used and tok.kind in {"col", "value"}
            ):
                break
            j += 1
        return j, distinct

    def metric_pass(self) -> None:  # noqa: PLR0912, PLR0915
        t = self.t
        group_target = bool(self.groups) or self.bucket is not None
        explicit: list[Metric] = []
        i = 0
        while i < len(t):
            tok = t[i]
            if tok.used or tok.kind not in {"kw:agg", "kw:rank", "kw:distinct"}:
                i += 1
                continue
            agg = tok.arg if tok.kind == "kw:agg" else None
            if tok.kind == "kw:distinct":
                agg = "count"
            j, distinct = self.next_unused_col(i + 1)
            distinct = distinct or tok.kind == "kw:distinct"
            nxt = self.at(j)
            if nxt is not None and nxt.kind == "row" and not nxt.used:
                tok.used = nxt.used = True
                explicit.append(Metric(agg="count"))
                i = j + 1
                continue
            if nxt is None or nxt.kind != "col" or nxt.used:
                if agg == "count":
                    tok.used = True
                    explicit.append(Metric(agg="count"))
                elif tok.kind == "kw:rank" and group_target:
                    tok.used = True  # "which country has the most?" → rows, ranked
                    self.sort = "metric_desc" if tok.arg == "desc" else "metric_asc"
                    self.limit = self.limit or (10 if self.which_plural else 1)
                i += 1
                continue
            col = nxt.col
            assert col is not None  # noqa: S101
            tok.used = nxt.used = True
            if tok.kind == "kw:rank":
                # "highest revenue": a ranking when there is something to rank, else max/min
                if group_target:
                    explicit.append(self.default_metric(col))
                    self.sort = "metric_desc" if tok.arg == "desc" else "metric_asc"
                    self.limit = self.limit or (1 if self.which and not self.which_plural else 10)
                elif col.kind == "date" or col.numeric:
                    explicit.append(
                        Metric(agg="max" if tok.arg == "desc" else "min", column=col.name)
                    )
                else:
                    self.fail = f"'{tok.text} {nxt.text}' needs something to rank by"
                    return
            elif agg == "count":
                if distinct or col.entity or nxt.plural:
                    explicit.append(Metric(agg="count_distinct", column=col.name))
                else:
                    explicit.append(Metric(agg="count", column=col.name))
            else:
                assert agg is not None  # noqa: S101
                if agg in {"sum", "avg"} and not col.numeric:
                    if agg == "sum" and col.entity:
                        explicit.append(Metric(agg="count_distinct", column=col.name))
                    else:
                        self.fail = f"'{tok.text}' of non-numeric '{col.name}'"
                        return
                else:
                    explicit.append(Metric(agg=agg, column=col.name))  # type: ignore[arg-type]
            i = j + 1

        # Bare measures ("revenue by country") and entities ("customers by country")
        bare: list[Metric] = []
        subjects: set[str] = set()
        for tok in t:
            if tok.used or tok.kind != "col" or tok.col is None:
                continue
            col = tok.col
            if col.numeric and not col.entity:
                bare.append(self.default_metric(col))
                tok.used = True
            elif col.entity and (tok.plural or tok.text == col.entity):
                bare.append(Metric(agg="count_distinct", column=col.name))
                tok.used = True
                if tok.subject:
                    subjects.add(col.name)
        metrics = self.metrics + explicit + bare
        if len(metrics) > 1 and subjects:
            # "revenue for products containing 'heart'": products only describe the filter
            metrics = [
                m for m in metrics if not (m.agg == "count_distinct" and m.column in subjects)
            ]
        if not metrics:
            # "lines with a negative quantity" counts rows; "show me every row" asks for a
            # listing, which this tool does not do, so rows alone need a filter or grouping.
            if self.filters or group_target:
                metrics = [Metric(agg="count")]
                for tok in t:
                    if tok.kind == "row":
                        tok.used = True
            else:
                self.fail = "no measure or count in the question"
                return
        unique: list[Metric] = []
        for m in metrics:
            if m not in unique:
                unique.append(m)
        if len(unique) > 3:
            self.fail = "more than three measures"
            return
        self.metrics = unique
        if self.which and self.sort is None:
            self.sort = "metric_desc"
            self.limit = self.limit or (10 if self.which_plural else 1)
        for tok in t:
            if tok.used:
                continue
            if tok.kind == "kw:all":
                self.limit = 100
                tok.used = True
            elif tok.kind in {"row", "kw:and", "kw:in", "kw:of"}:
                tok.used = True

    def default_metric(self, col: ColumnInfo) -> Metric:
        if col.entity:
            return Metric(agg="count_distinct", column=col.name)
        if not col.numeric:
            return Metric(agg="count", column=col.name)
        return Metric(agg="sum" if col.additive else "avg", column=col.name)

    def plan(self) -> QueryPlan:
        sort = self.sort
        limit = self.limit
        if self.bucket and sort is None:
            sort, limit = "group_asc", limit or 100
        if self.groups and sort is None:
            sort = "metric_desc"
        dims = len(self.groups) + (1 if self.bucket else 0)
        return QueryPlan(
            metrics=self.metrics,
            group_by=self.groups,
            time_bucket=self.bucket,
            filters=self.filters,
            sort=sort if dims else None,
            limit=min(limit or (100 if self.bucket else 20), 100),
        )


def _num(tok: Tok) -> Scalar:
    n = tok.number or 0.0
    return int(n) if float(n).is_integer() else n


def _pattern(b: _Builder) -> str:
    base = b.pattern
    if base == "aggregate":
        if b.groups:
            base = "breakdown"
        elif len(b.metrics) == 1 and b.metrics[0].agg == "count":
            base = "count_rows" if b.metrics[0].column is None else "count"
        elif len(b.metrics) == 1 and b.metrics[0].agg == "count_distinct":
            base = "count_distinct"
    return base + ("+filters" if b.filters else "")


def parse_question(question: str, schema: DatasetSchema) -> Parsed:
    """Return a plan, or the reason the rules cannot interpret the question."""
    if not question.strip():
        return Parsed(None, reason="empty question")
    toks = _lex(question, _Lexicon(schema))
    unknown = [
        t.text
        for t in toks
        if t.kind == "word" and t.text not in STOPWORDS and t.text not in FILLER_VERBS
    ]
    if unknown:
        return Parsed(None, reason="unrecognised words", unknown=unknown)
    b = _Builder(toks, schema)
    b.run()
    if b.fail:
        return Parsed(None, reason=b.fail)
    leftover = [
        t.text
        for t in toks
        if not t.used and not (t.kind == "word" and (t.text in STOPWORDS or t.text in FILLER_VERBS))
    ]
    if leftover:
        return Parsed(None, reason="parts of the question were not used", unknown=leftover)
    return Parsed(b.plan(), pattern=_pattern(b))
