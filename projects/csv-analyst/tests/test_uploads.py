"""Uploads: only small text CSVs are accepted, profiled, and deleted after the TTL."""

from __future__ import annotations

import json
import time

import pytest

from reluai_csv.datasets import UploadRejectedError, UploadStore
from reluai_csv.settings import CsvSettings

GOOD = (
    b"Region,Product,Units Sold,unit price,Order Date\n"
    b"North,Widget,10,2.50,2024-01-03\n"
    b"South,Gadget,4,3.00,2024-02-11\n"
    b"North,Gadget,7,3.00,2024-02-15\n"
)


def reject_code(settings: CsvSettings, data: bytes, name: str = "data.csv") -> str:
    with pytest.raises(UploadRejectedError) as info:
        UploadStore(settings).save(data, name)
    return info.value.code


def test_profiles_a_good_file(upload_settings: CsvSettings) -> None:
    upload = UploadStore(upload_settings).save(GOOD, "sales report.csv")
    assert len(upload.id) == 32
    assert upload.label == "sales report.csv"
    assert upload.profile.rows == 3
    kinds = {c.name: c.kind for c in upload.profile.columns}
    assert kinds["Units Sold"] == "integer"
    assert kinds["unit price"] == "number"
    assert kinds["Order Date"] == "date"
    schema = upload.schema()
    assert schema.default_date == "Order Date"
    units = schema.column("units sold")
    assert units is not None and units.entity is None  # a measure, not a thing to count
    price = schema.column("unit price")
    assert price is not None and not price.additive  # prices are averaged, not summed


@pytest.mark.parametrize(
    ("data", "name", "code"),
    [
        (b"", "a.csv", "empty_file"),
        (b"   \n\n", "a.csv", "empty_file"),
        (b"a,b\n1,2\n", "a.xlsx", "not_csv"),
        (b"a,b\n1,2\n", "payload.exe", "not_csv"),
        (b"PK\x03\x04" + b"\x00" * 100, "sheet.csv", "not_csv"),  # an xlsx renamed
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 50, "image.csv", "not_csv"),
        (b"%PDF-1.7\n", "doc.csv", "not_csv"),
        (b"MZ\x90\x00", "a.csv", "not_csv"),
        (b"a,b\n1,\x002\n", "a.csv", "not_csv"),
        (b"a,b,c\n", "a.csv", "no_rows"),
    ],
)
def test_rejects(upload_settings: CsvSettings, data: bytes, name: str, code: str) -> None:
    assert reject_code(upload_settings, data, name) == code


def test_size_row_and_column_limits(upload_settings: CsvSettings) -> None:
    small = upload_settings.model_copy(
        update={"upload_max_bytes": 2048, "upload_max_rows": 5, "upload_max_columns": 3}
    )
    assert reject_code(small, b"a,b\n" + b"1,2\n" * 1000) == "file_too_large"
    assert reject_code(small, b"a,b\n" + b"1,2\n" * 6) == "too_many_rows"
    assert reject_code(small, b"a,b,c,d\n1,2,3,4\n") == "too_many_columns"
    assert UploadStore(small).save(b"a,b\n" + b"1,2\n" * 5, "ok.csv").profile.rows == 5


def test_windows_1252_and_bom(upload_settings: CsvSettings) -> None:
    latin = "city,amount\nZürich,£5\nMálaga,€7\n".encode("cp1252")
    upload = UploadStore(upload_settings).save(latin, "latin.csv")
    city = next(c for c in upload.profile.columns if c.name == "city")
    assert {v for v, _ in city.top_values} == {"Zürich", "Málaga"}
    bom = "﻿name,score\nAda,3\n".encode()
    upload = UploadStore(upload_settings).save(bom, "bom.csv")
    assert upload.profile.columns[0].name == "name"


def test_findings(upload_settings: CsvSettings) -> None:
    data = (
        b"id,customer,amount,note\n"
        b'1,=HYPERLINK("http://x"),"1,200",ok\n'
        b'2,@SUM(A1),"1,250", padded \n'
        b'3,Bob,"2,000",\n'
        b'3,Bob,"2,000",\n'
    )
    upload = UploadStore(upload_settings).save(data, "f.csv")
    found = {(f.code, f.column) for f in upload.profile.findings}
    assert ("formula_like_text", "customer") in found
    assert ("numbers_stored_as_text", "amount") in found
    assert ("duplicate_rows", None) in found
    assert ("missing_values", "note") in found or ("mostly_missing", "note") in found
    assert ("untrimmed_text", "note") in found
    messages = " ".join(f.message for f in upload.profile.findings)
    assert "2 values in 'customer' start with" in messages


def test_expired_uploads_are_gone(upload_settings: CsvSettings) -> None:
    store = UploadStore(upload_settings)
    upload = store.save(GOOD, "a.csv")
    meta_path = upload_settings.upload_dir / f"{upload.id}.json"
    meta = json.loads(meta_path.read_text())
    meta["expires_at"] = time.time() - 1
    meta_path.write_text(json.dumps(meta))
    assert store.get(upload.id) is None
    assert store.purge() == 1
    assert not upload.path.exists()
    assert not meta_path.exists()


def test_storage_cap_removes_the_oldest(upload_settings: CsvSettings) -> None:
    capped = upload_settings.model_copy(update={"max_stored_uploads": 2})
    store = UploadStore(capped)
    first = store.save(GOOD, "1.csv")
    time.sleep(0.01)
    store.save(GOOD, "2.csv")
    time.sleep(0.01)
    store.save(GOOD, "3.csv")
    store.purge()
    assert store.get(first.id) is None
    assert len(list(capped.upload_dir.glob("*.json"))) == 2


@pytest.mark.parametrize("upload_id", ["../etc/passwd", "retail", "A" * 32, "0" * 31, ""])
def test_ids_are_checked(upload_settings: CsvSettings, upload_id: str) -> None:
    assert UploadStore(upload_settings).get(upload_id) is None


def test_file_names_are_cleaned(upload_settings: CsvSettings) -> None:
    upload = UploadStore(upload_settings).save(GOOD, "../../<script>alert(1)</script>.csv")
    assert "/" not in upload.label
    assert "<" not in upload.label
