"""Question-answering evaluation on the bundled sample document.

Every question has expected page(s) and the facts a correct answer must contain (any of a
few phrasings); "unanswerable" questions are about things the document does not cover, and
the correct response to them is to abstain. Checks are mechanical, so a run is
reproducible and needs no judge model:

* **correct**: answerable → not abstained and every required fact present; unanswerable →
  abstained.
* **retrieved**: an expected page is among the retrieved passages (retrieval recall).
* **cited expected**: the answer cites a passage on an expected page (citation precision).

The set is split in two. Thresholds (e.g. when the extractive answerer abstains) were tuned
on ``dev`` only; ``held_out`` is reported separately so tuning cannot flatter the result.
"""

from __future__ import annotations

import platform
import re
import statistics
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from reluai_core.db import Database
from reluai_docs import service
from reluai_docs.models import EvaluationRun
from reluai_docs.questions import QUESTIONS, EvalQuestion
from reluai_docs.sample import SAMPLE
from reluai_docs.schemas import QuestionRequest
from reluai_docs.settings import DocsSettings

_SPACE = re.compile(r"\s+")
Mode = Literal["auto", "extractive"]


def _norm(text: str) -> str:
    text = text.lower().replace("’", "'").replace("“", '"').replace("”", '"').replace("‐", "-")
    return _SPACE.sub(" ", text)


def facts_present(answer: str, must: tuple[tuple[str, ...], ...]) -> bool:
    a = _norm(answer)
    return all(any(_norm(alt) in a for alt in alts) for alts in must)


@dataclass(slots=True)
class ItemResult:
    id: str
    question: str
    kind: str
    split: str
    correct: bool
    abstained: bool
    retrieved: bool
    cited_expected: bool
    latency_ms: int
    tokens: int
    answer: str
    method: str
    provider: str | None


@dataclass(slots=True)
class Summary:
    label: str
    questions: int
    correct: int
    tokens: int
    median_latency_ms: int
    p95_latency_ms: int
    metrics: dict[str, float | int]
    environment: dict[str, Any]
    results: list[ItemResult] = field(default_factory=list)


def _pct(values: list[bool]) -> float:
    return round(100 * sum(values) / len(values), 1) if values else 0.0


def _p95(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]


def run_evaluation(
    db: Database,
    settings: DocsSettings,
    *,
    label: str,
    mode: Mode,
    chain_factory: service.ChainFactory | None = None,
    embedder: service.EmbedderLoader | None = None,
    questions: tuple[EvalQuestion, ...] = QUESTIONS,
) -> Summary | None:
    rec = service.ensure_sample(db, settings)
    if rec is None:
        return None
    factory = chain_factory or (lambda _external: None)
    results: list[ItemResult] = []
    for q in questions:
        t0 = time.perf_counter()
        out = service.ask(
            db,
            settings,
            rec,
            QuestionRequest(question=q.question, mode=mode, allow_external=True),
            visitor=None,
            chain_factory=factory,
            embedder=embedder,
        )
        latency = round((time.perf_counter() - t0) * 1000)
        expected = set(q.pages)
        pages_of = {p.number: set(range(p.page_from, p.page_to + 1)) for p in out.passages}
        retrieved = any(pages & expected for pages in pages_of.values())
        cited = any(pages_of.get(n, set()) & expected for n in out.citations)
        if q.kind == "answerable":
            correct = not out.abstained and facts_present(out.answer, q.must)
        else:
            correct = out.abstained
        results.append(
            ItemResult(
                id=q.id,
                question=q.question,
                kind=q.kind,
                split=q.split,
                correct=correct,
                abstained=out.abstained,
                retrieved=retrieved,
                cited_expected=cited,
                latency_ms=latency,
                tokens=out.tokens,
                answer=out.answer[:600],
                method=out.method,
                provider=out.provider,
            )
        )
    answerable = [r for r in results if r.kind == "answerable"]
    unanswerable = [r for r in results if r.kind == "unanswerable"]
    metrics: dict[str, float | int] = {
        "accuracy": _pct([r.correct for r in results]),
        "answerable_accuracy": _pct([r.correct for r in answerable]),
        "abstention_accuracy": _pct([r.correct for r in unanswerable]),
        "false_abstentions": sum(1 for r in answerable if r.abstained),
        "retrieval_recall": _pct([r.retrieved for r in answerable]),
        "citation_precision": _pct([r.cited_expected for r in answerable if not r.abstained]),
        "model_answers": sum(1 for r in results if r.method == "model"),
    }
    for split in ("dev", "held_out"):
        part = [r for r in results if r.split == split]
        metrics[f"{split}_accuracy"] = _pct([r.correct for r in part])
        metrics[f"{split}_questions"] = len(part)
    latencies = [r.latency_ms for r in results]
    return Summary(
        label=label,
        questions=len(results),
        correct=sum(r.correct for r in results),
        tokens=sum(r.tokens for r in results),
        median_latency_ms=round(statistics.median(latencies)) if latencies else 0,
        p95_latency_ms=_p95(latencies),
        metrics=metrics,
        environment={
            "search": rec.search_mode,
            "embedding_model": rec.embedding_model,
            "providers": ", ".join(sorted({r.provider for r in results if r.provider})) or None,
            "python": platform.python_version(),
            "machine": platform.machine(),
            "cpus": __import__("os").cpu_count(),
        },
        results=results,
    )


def record_run(db: Database, summary: Summary) -> None:
    with db.session() as s:
        s.add(
            EvaluationRun(
                label=summary.label,
                document=SAMPLE.id,
                questions=summary.questions,
                correct=summary.correct,
                tokens=summary.tokens,
                median_latency_ms=summary.median_latency_ms,
                p95_latency_ms=summary.p95_latency_ms,
                metrics=summary.metrics,
                environment=summary.environment,
                results=[asdict(r) for r in summary.results],
            )
        )
