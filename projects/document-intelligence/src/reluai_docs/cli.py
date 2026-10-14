"""``reluai-docs``: fetch the model and sample, build the sample, ask, evaluate; invoices."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from reluai_core.logging import configure_logging

if TYPE_CHECKING:
    from reluai_core.db import Database
    from reluai_docs.service import ChainFactory
    from reluai_docs.settings import DocsSettings

HF = "https://huggingface.co/BAAI/bge-small-en-v1.5/resolve/{rev}/{path}"
# (published path, local name, SHA-256, max bytes); the same pins as artifacts/manifest.yaml
MODEL_FILES = (
    ("onnx/model.onnx", "bge-small-en-v1.5.onnx",
     "828e1496d7fabb79cfa4dcd84fa38625c0d3d21da474a00f08db0f559940cf35", 150_000_000),
    ("tokenizer.json", "bge-small-en-v1.5.tokenizer.json",
     "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66", 2_000_000),
)  # fmt: skip


def _db() -> Database:
    from reluai_core.db import Database
    from reluai_core.settings import get_core_settings

    return Database(get_core_settings(), application_name="reluai-docs-cli")


def _chain(provider: str, db: Database) -> ChainFactory:
    from reluai_inference.chain import ProviderChain
    from reluai_inference.config import build_chain, get_inference_settings

    if provider == "extractive":
        return lambda _external: None
    chain = build_chain(get_inference_settings(), db, role="answer")
    chosen = [p for p in chain.providers if p.available() and provider in {"chain", p.name}]
    if not chosen:
        raise SystemExit(f"provider {provider!r} is not configured; nothing was run")
    return lambda _external: ProviderChain(chosen, chain.ledger)


def _fetch(settings: DocsSettings, out: Path | None) -> int:
    from reluai_datasets.fetch import download
    from reluai_docs.embedding import MODEL_REVISION
    from reluai_docs.sample import SAMPLE

    out = out or settings.data_dir
    for path, name, sha, limit in MODEL_FILES:
        target = out / "models" / name
        url = HF.format(rev=MODEL_REVISION, path=path)
        download(url, target, max_bytes=limit, expected_sha256=sha)
        print(target)
    target = out / "source" / SAMPLE.filename
    download(SAMPLE.file_url, target, max_bytes=20_000_000, expected_sha256=SAMPLE.sha256)
    print(target)
    return 0


def _build_sample(settings: DocsSettings, pdf: Path | None, out: Path | None, verify: bool) -> int:
    from reluai_docs.sample import SAMPLE, build_sample

    out = out or settings.data_dir
    payload = build_sample(
        pdf or out / "source" / SAMPLE.filename,
        out / "sample.json",
        model_dir=out / "models",
        chunk_words=settings.chunk_words,
        chunk_overlap=settings.chunk_overlap,
        verify=verify,
    )
    summary = {k: payload[k] for k in ("page_count", "chunks", "embedding_model")}
    summary |= {"chars": len(payload["text"]), "headings": len(payload["outline"])}
    print(json.dumps(summary))
    return 0


def _ask(settings: DocsSettings, question: str, provider: str) -> int:
    from reluai_docs import service
    from reluai_docs.schemas import QuestionRequest

    db = _db()
    try:
        rec = service.ensure_sample(db, settings)
        if rec is None:
            raise SystemExit("the sample is not built; run build-sample first")
        mode: Literal["auto", "extractive"] = "extractive" if provider == "extractive" else "auto"
        out = service.ask(
            db,
            settings,
            rec,
            QuestionRequest(question=question, mode=mode),
            visitor=None,
            chain_factory=_chain(provider, db),
        )
    finally:
        db.dispose()
    print(json.dumps(out.model_dump(exclude={"passages"}), indent=2, default=str))
    for p in out.passages:
        print(f"[{p.number}] p.{p.page_from}-{p.page_to} {p.heading}: {p.text[:160]}")
    return 0


def _evaluate(settings: DocsSettings, provider: str, *, record: bool, show: bool) -> int:
    from reluai_docs.evaluation import record_run, run_evaluation

    db = _db()
    try:
        mode: Literal["auto", "extractive"] = "extractive" if provider == "extractive" else "auto"
        summary = run_evaluation(
            db, settings, label=provider, mode=mode, chain_factory=_chain(provider, db)
        )
        if summary is None:
            raise SystemExit("the sample is not built; run build-sample first")
        if show:
            for r in summary.results:
                mark = "PASS" if r.correct else "FAIL"
                print(f"{mark} {r.split:8} {r.id:28} {r.answer[:150]!r}")
        totals = {
            "correct": summary.correct,
            "questions": summary.questions,
            "median_ms": summary.median_latency_ms,
            "p95_ms": summary.p95_latency_ms,
        }
        print(json.dumps(summary.metrics | totals))
        # A model run in which any answer fell back to extractive is not that model's score.
        if provider != "extractive" and any(r.method != "model" for r in summary.results):
            print("some answers fell back to extractive; the run was not recorded")
        elif record:
            record_run(db, summary)
    finally:
        db.dispose()
    return 0


def _invoices_build(settings: DocsSettings, canonical: Path, out: Path | None) -> int:
    from reluai_docs.invoices.records import evaluation_set, select_invoices, write_set

    out = out or settings.data_dir
    out.mkdir(parents=True, exist_ok=True)
    docs = evaluation_set(select_invoices(canonical))
    write_set(docs, out / "invoices.json")
    scans = sum(d.scanned for d in docs)
    print(json.dumps({"documents": len(docs), "scans": scans, "path": str(out / "invoices.json")}))
    return 0


def _invoices_evaluate(settings: DocsSettings, *, record: bool, show: bool, split: str) -> int:
    from reluai_docs.invoices.evaluate import summarise_run
    from reluai_docs.invoices.service import evaluate, record_run

    results = [r for r in evaluate(settings) if split in ("all", r.split)]
    if not results:
        raise SystemExit("the invoice set is not built; run `reluai-docs invoices build` first")
    if show:
        for r in results:
            mark = "EXACT" if r.comparison.exact else "WRONG"
            flag = "flagged" if r.comparison.needs_review else "       "
            print(f"{mark} {flag} {r.id:24} {r.ms:6} ms  {'; '.join(r.comparison.mismatches[:2])}")
    print(json.dumps(summarise_run(results), indent=2))
    if record and split == "all":
        db = _db()
        try:
            record_run(db, results)
        finally:
            db.dispose()
    elif record:
        print("only a run over the whole set is recorded")
    return 0


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0911
    parser = argparse.ArgumentParser(prog="reluai-docs")
    sub = parser.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="Download the embedding model and the sample PDF (verified)")
    f.add_argument("--out", type=Path, default=None, help="data dir (default: settings)")
    q = sub.add_parser("quantize", help="Write an INT8 copy of the embedding model")
    q.add_argument("--model-dir", type=Path, default=None)
    b = sub.add_parser("build-sample", help="Read, index and embed the sample PDF into JSON")
    b.add_argument("--pdf", type=Path, default=None)
    b.add_argument("--out", type=Path, default=None, help="data dir (default: settings)")
    b.add_argument("--no-verify", action="store_true", help="skip the SHA-256 check (tests)")
    a = sub.add_parser("ask", help="Ask the sample document a question")
    a.add_argument("question")
    a.add_argument("--provider", default="extractive", help="extractive, groq, local or chain")
    e = sub.add_parser("evaluate", help="Run the question set on the sample and record it")
    e.add_argument("--provider", default="extractive", help="extractive, groq, local or chain")
    e.add_argument("--no-record", action="store_true")
    e.add_argument("--show", action="store_true", help="print every answer")
    inv = sub.add_parser("invoices", help="Invoice extraction: build the set, evaluate")
    isub = inv.add_subparsers(dest="invoices_cmd", required=True)
    ib = isub.add_parser("build", help="Draw the invoice set from the canonical retail data")
    ib.add_argument("--canonical", type=Path, required=True, help="online-retail-ii.parquet")
    ib.add_argument("--out", type=Path, default=None, help="data dir (default: settings)")
    ie = isub.add_parser("evaluate", help="Extract every invoice and compare with the records")
    ie.add_argument("--no-record", action="store_true")
    ie.add_argument("--show", action="store_true", help="print every document")
    ie.add_argument("--split", choices=("all", "dev", "held_out"), default="all")
    args = parser.parse_args(argv)
    configure_logging(level="WARNING", json=False)
    logging.getLogger().handlers[:] = [logging.StreamHandler(sys.stderr)]

    from reluai_docs.settings import get_docs_settings

    settings = get_docs_settings()
    if args.cmd == "fetch":
        return _fetch(settings, args.out)
    if args.cmd == "invoices":
        if args.invoices_cmd == "build":
            return _invoices_build(settings, args.canonical, args.out)
        return _invoices_evaluate(
            settings, record=not args.no_record, show=args.show, split=args.split
        )
    if args.cmd == "quantize":
        from reluai_docs.embedding import quantize

        print(quantize(args.model_dir or settings.model_dir))
        return 0
    if args.cmd == "build-sample":
        return _build_sample(settings, args.pdf, args.out, verify=not args.no_verify)
    if args.cmd == "ask":
        return _ask(settings, args.question, args.provider)
    return _evaluate(settings, args.provider, record=not args.no_record, show=args.show)


if __name__ == "__main__":
    sys.exit(main())
