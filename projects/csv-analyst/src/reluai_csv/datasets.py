"""The bundled retailer table and visitor uploads.

The bundled table is built once, at image build time, from the verified Online Retail II
download, and opened read-only for every query. Uploads are converted into their own small
DuckDB file in the API container's private temporary storage and deleted after an hour. The
original upload is never kept and its contents are never logged.
"""

from __future__ import annotations

import json
import re
import secrets
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import duckdb

from reluai_csv import sandbox
from reluai_csv.compile import quote_ident
from reluai_csv.profile import Profile, profile_table
from reluai_csv.schema import ColumnInfo, DatasetSchema
from reluai_csv.settings import CsvSettings

BUNDLED_ID = "retail"
BUNDLED_TABLE = "sales"
UPLOAD_TABLE = "uploaded"
_UPLOAD_ID = re.compile(r"^[0-9a-f]{32}$")

# --------------------------------------------------------------------------- bundled table
_BUNDLED_SQL = """
CREATE TABLE sales AS
SELECT
    invoice                                   AS invoice_no,
    CAST(invoice_date AS TIMESTAMP)           AS invoiced_at,
    stock_code,
    description,
    CAST(quantity AS INTEGER)                 AS quantity,
    CAST(price AS DECIMAL(12, 3))             AS unit_price,
    CAST(quantity * price AS DECIMAL(14, 3))  AS revenue,
    customer_id,
    country,
    invoice LIKE 'C%'                         AS is_cancellation
FROM read_parquet(?)
"""

BUNDLED_META: dict[str, dict[str, Any]] = {
    "invoice_no": {
        "description": "Invoice number. A leading C marks a cancellation.",
        "synonyms": ("invoice number", "invoice no", "invoice", "orders", "order", "purchases"),
        "entity": "invoices",
        "title": "invoice number",
    },
    "invoiced_at": {
        "description": "Date and time of the invoice (1 Dec 2009 to 9 Dec 2011).",
        "synonyms": ("date", "invoice date", "time"),
        "title": "invoice date",
    },
    "stock_code": {
        "description": "Product code.",
        "synonyms": ("stock code", "product code", "sku"),
        "entity": "product codes",
    },
    "description": {
        "description": "Product name as written on the invoice.",
        "synonyms": ("product", "item", "items", "product name"),
        "entity": "products",
        "title": "product",
    },
    "quantity": {
        "description": "Units on the line; negative on cancellations.",
        "synonyms": ("quantity", "units", "qty", "units sold", "items sold"),
    },
    "unit_price": {
        "description": "Price per unit, in pounds sterling.",
        "synonyms": ("price", "unit price", "prices"),
        "additive": False,
    },
    "revenue": {
        "description": (
            "Quantity × unit price, in pounds sterling. Net: cancellations are negative."
        ),
        "synonyms": (
            "revenue",
            "sales",
            "turnover",
            "takings",
            "sales value",
            "spend",
            "spent",
            "spending",
            "amount",
        ),
    },
    "customer_id": {
        "description": "Anonymised customer number; missing on some lines.",
        "synonyms": ("customer id", "customer number"),
        "entity": "customers",
        "title": "customer ID",
    },
    "country": {
        "description": "The customer's country.",
        "synonyms": ("country", "market"),
        "entity": "countries",
        "value_aliases": (
            ("uk", "United Kingdom"),
            ("britain", "United Kingdom"),
            ("great britain", "United Kingdom"),
            ("ireland", "EIRE"),
            ("united states", "USA"),
            ("america", "USA"),
            ("south africa", "RSA"),
            ("uae", "United Arab Emirates"),
            ("south korea", "Korea"),
            ("czechia", "Czech Republic"),
        ),
    },
    "is_cancellation": {
        "description": "True on cancellation lines (invoice number starts with C).",
        "synonyms": ("cancellation", "cancelled", "canceled", "cancellations"),
        "title": "cancellation",
    },
}

BUNDLED_EXAMPLES = (
    "Top 10 products by revenue",
    "Revenue per month",
    "How many customers are in Germany?",
    "Average unit price by country",
    "Most common countries",
    "Revenue by country in 2011, excluding the UK",
    "How many cancelled invoices were there in 2010?",
    "Lines with quantity over 1000",
)


def build_bundled(canonical_dir: Path, out_dir: Path) -> Path:
    """Create the read-only DuckDB file and its profile from the canonical Parquet."""
    source = canonical_dir / "online-retail-ii.parquet"
    if not source.is_file():
        raise FileNotFoundError(f"canonical dataset not found: {source}")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "retail.duckdb"
    tmp = out_dir / "retail.duckdb.partial"
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    try:
        con.execute(_BUNDLED_SQL, [str(source)])
        profile = profile_table(con, BUNDLED_TABLE)
    finally:
        con.close()
    tmp.replace(target)
    (out_dir / "retail.profile.json").write_text(json.dumps(profile.to_json()), encoding="utf-8")
    return target


def schema_from_profile(
    profile: Profile, table: str, meta: dict[str, dict[str, Any]] | None = None
) -> DatasetSchema:
    meta = meta or {}
    cols: list[ColumnInfo] = []
    for c in profile.columns:
        m = meta.get(c.name) or _auto_meta(c.name, c.kind)
        cols.append(
            ColumnInfo(
                name=c.name,
                kind=c.kind,
                sql_type=c.sql_type,
                description=m.get("description", ""),
                synonyms=tuple(m.get("synonyms", ())),
                entity=m.get("entity"),
                values=tuple(c.values),
                value_aliases=tuple(m.get("value_aliases", ())),
                distinct=c.distinct,
                additive=bool(m.get("additive", True)),
                title=m.get("title"),
            )
        )
    dates = [c for c in cols if c.kind == "date"]
    numeric = [c for c in cols if c.numeric and not c.name.lower().endswith("id")]
    measure = "revenue" if any(c.name == "revenue" for c in cols) else None
    if measure is None and len(numeric) == 1:
        measure = numeric[0].name
    return DatasetSchema(
        table=table,
        columns=tuple(cols),
        row_noun="invoice lines" if table == BUNDLED_TABLE else "rows",
        default_date=dates[0].name if len(dates) >= 1 else None,
        default_measure=measure,
    )


_NON_ADDITIVE = re.compile(
    r"(price|rate|percent|pct|ratio|avg|average|mean|score|age|temp|lat|lon|rating|margin)", re.I
)


def _auto_meta(name: str, kind: str) -> dict[str, Any]:
    """Words for an uploaded column, from its header: "order_date" → "order date"."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    label = re.sub(r"[_\-.]+", " ", spaced).strip().lower()
    synonyms = {label}
    entity = None
    identifier = re.search(r"\b(id|code|key|number|no)$", label) is not None
    # Text columns name things (products, regions); integers only when the header says so
    # (customer_id), so "units" or "quantity" stay measures.
    if kind == "text" or (kind == "integer" and identifier):
        base = re.sub(r"\s*(id|code|key|name|number|no)$", "", label).strip() or label
        if base:
            entity = base if base.endswith("s") else base + "s"
            synonyms.add(base)
    return {
        "synonyms": tuple(sorted(synonyms)),
        "entity": entity,
        "additive": not _NON_ADDITIVE.search(name),
    }


@lru_cache(maxsize=4)
def _bundled_profile(path: str, mtime: float) -> Profile:
    return Profile.from_json(json.loads(Path(path).read_text(encoding="utf-8")))


def bundled_profile(settings: CsvSettings) -> Profile:
    path = settings.bundled_profile
    if not path.is_file():
        raise FileNotFoundError("bundled dataset has not been built")
    return _bundled_profile(str(path), path.stat().st_mtime)


def bundled_schema(settings: CsvSettings) -> DatasetSchema:
    return schema_from_profile(bundled_profile(settings), BUNDLED_TABLE, BUNDLED_META)


# --------------------------------------------------------------------------- uploads
class UploadRejectedError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class Upload:
    id: str
    label: str
    created_at: float
    expires_at: float
    path: Path
    profile: Profile

    def schema(self) -> DatasetSchema:
        return schema_from_profile(self.profile, UPLOAD_TABLE)


_BINARY_MAGIC = (
    b"PK\x03\x04",  # zip, xlsx, docx
    b"%PDF",
    b"\x89PNG",
    b"GIF8",
    b"\xff\xd8\xff",  # JPEG
    b"MZ",  # Windows executable
    b"\x7fELF",
    b"\xd0\xcf\x11\xe0",  # old Office formats (xls)
    b"SQLite format 3",
    b"\x1f\x8b",  # gzip
)
_ALLOWED_SUFFIXES = {".csv", ".tsv", ".txt", ""}


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _safe_label(filename: str | None) -> str:
    name = Path(filename or "upload.csv").name
    name = re.sub(r"[^\w .()-]", "_", name)[:60]
    return name or "upload.csv"


class UploadStore:
    def __init__(self, settings: CsvSettings) -> None:
        self.settings = settings
        self.root = settings.upload_dir

    def _db_path(self, upload_id: str) -> Path:
        return self.root / f"{upload_id}.duckdb"

    def _meta_path(self, upload_id: str) -> Path:
        return self.root / f"{upload_id}.json"

    def purge(self, now: float | None = None) -> int:
        """Delete expired uploads, and the oldest ones beyond the storage cap."""
        if not self.root.is_dir():
            return 0
        now = now or time.time()
        removed = 0
        metas = sorted(self.root.glob("*.json"), key=lambda p: p.stat().st_mtime)
        keep = len(metas)
        for meta in metas:
            upload_id = meta.stem
            try:
                expires = float(json.loads(meta.read_text(encoding="utf-8"))["expires_at"])
            except (OSError, ValueError, KeyError):
                expires = 0
            if expires < now or keep > self.settings.max_stored_uploads:
                sandbox.forget(self._db_path(upload_id))
                self._db_path(upload_id).unlink(missing_ok=True)
                meta.unlink(missing_ok=True)
                removed += 1
                keep -= 1
        for stray in self.root.glob("*.partial*"):
            if stray.stat().st_mtime < now - 300:
                stray.unlink(missing_ok=True)
        return removed

    def get(self, upload_id: str) -> Upload | None:
        if not _UPLOAD_ID.match(upload_id):
            return None
        meta_path, db_path = self._meta_path(upload_id), self._db_path(upload_id)
        if not meta_path.is_file() or not db_path.is_file():
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if float(meta["expires_at"]) < time.time():
            return None
        return Upload(
            id=upload_id,
            label=meta["label"],
            created_at=float(meta["created_at"]),
            expires_at=float(meta["expires_at"]),
            path=db_path,
            profile=Profile.from_json(meta["profile"]),
        )

    def save(self, data: bytes, filename: str | None) -> Upload:
        s = self.settings
        if not data.strip():
            raise UploadRejectedError("empty_file", "The file is empty.")
        if len(data) > s.upload_max_bytes:
            raise UploadRejectedError(
                "file_too_large", f"Files can be up to {s.upload_max_bytes // 1000:,} KB."
            )
        if Path(filename or "").suffix.lower() not in _ALLOWED_SUFFIXES:
            raise UploadRejectedError("not_csv", "Upload a .csv, .tsv or .txt file.")
        head = data[:8192]
        if any(head.startswith(m) for m in _BINARY_MAGIC) or b"\x00" in head:
            raise UploadRejectedError(
                "not_csv", "This is not a text CSV file (it looks like a binary or Excel file)."
            )
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.purge()
        upload_id = secrets.token_hex(16)
        csv_path = self.root / f"{upload_id}.partial.csv"
        db_tmp = self.root / f"{upload_id}.partial.duckdb"
        csv_path.write_text(_decode(data), encoding="utf-8")
        try:
            profile = self._load(csv_path, db_tmp)
        except UploadRejectedError:
            db_tmp.unlink(missing_ok=True)
            raise
        except duckdb.Error as exc:
            db_tmp.unlink(missing_ok=True)
            reason = str(exc).splitlines()[0][:160]
            raise UploadRejectedError(
                "unreadable_csv", f"The file could not be read as CSV ({reason})."
            ) from exc
        finally:
            csv_path.unlink(missing_ok=True)
        db_tmp.replace(self._db_path(upload_id))
        now = time.time()
        meta = {
            "label": _safe_label(filename),
            "created_at": now,
            "expires_at": now + s.upload_ttl_seconds,
            "profile": profile.to_json(),
        }
        self._meta_path(upload_id).write_text(json.dumps(meta), encoding="utf-8")
        found = self.get(upload_id)
        if found is None:  # pragma: no cover - written just above
            raise UploadRejectedError("storage_error", "The upload could not be stored.")
        return found

    def _load(self, csv_path: Path, db_path: Path) -> Profile:
        s = self.settings
        con = duckdb.connect(
            str(db_path),
            config={
                "threads": 1,
                "memory_limit": s.query_memory_limit,
                "autoinstall_known_extensions": False,
                "autoload_known_extensions": False,
            },
        )
        try:
            # The only file this connection reads is the converted upload written just above.
            con.execute(
                f"CREATE TABLE {UPLOAD_TABLE} AS SELECT * FROM read_csv(?, header = true, "  # noqa: S608
                f"auto_detect = true, sample_size = -1, null_padding = true) "
                f"LIMIT {s.upload_max_rows + 1}",
                [str(csv_path)],
            )
            con.execute("SET enable_external_access = false")
            described = con.execute(f"DESCRIBE {UPLOAD_TABLE}").fetchall()
            if len(described) > s.upload_max_columns:
                raise UploadRejectedError(
                    "too_many_columns", f"Files can have up to {s.upload_max_columns} columns."
                )
            count_row = con.execute(f"SELECT count(*) FROM {UPLOAD_TABLE}").fetchone()  # noqa: S608
            rows = int(count_row[0]) if count_row else 0
            if rows == 0:
                raise UploadRejectedError("no_rows", "The file has a header but no data rows.")
            if rows > s.upload_max_rows:
                raise UploadRejectedError(
                    "too_many_rows", f"Files can have up to {s.upload_max_rows:,} rows."
                )
            for i, (name, *_rest) in enumerate(described, start=1):
                text = str(name)
                if not text.strip() or len(text) > 64 or any(ord(ch) < 32 for ch in text):
                    con.execute(
                        f"ALTER TABLE {UPLOAD_TABLE} RENAME COLUMN {quote_ident(text)} "
                        f"TO {quote_ident(f'column_{i}')}"
                    )
            return profile_table(con, UPLOAD_TABLE)
        finally:
            con.close()
