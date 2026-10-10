"""Answering end to end, without a database: rules first, then the optional model."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from reluai_csv import service
from reluai_csv.datasets import BUNDLED_ID, UploadStore
from reluai_csv.llm import PLAN_TOOL, REFUSE_TOOL
from reluai_csv.sandbox import QueryTimeoutError
from reluai_csv.schemas import AskRequest, AskResponse
from reluai_csv.settings import CsvSettings
from reluai_inference.chain import ProviderChain
from reluai_inference.providers import DeterministicProvider
from reluai_inference.types import ChatRequest, ChatResponse, ToolCall

UPLOAD = b"team,points,played_on\nRed,3,2024-01-06\nBlue,1,2024-01-06\nRed,0,2024-01-13\n"


def scripted(name: str, arguments: str, calls: list[ChatRequest]) -> Callable[[], ProviderChain]:
    def handler(request: ChatRequest) -> ChatResponse:
        calls.append(request)
        return ChatResponse(
            provider="",
            model="",
            content=None,
            tool_calls=[ToolCall(id="c1", name=name, arguments=arguments)],
        )

    return lambda: ProviderChain([DeterministicProvider(handler, name="scripted")])


def never_called() -> ProviderChain:
    raise AssertionError("the model must not be asked")


def ask(
    settings: CsvSettings,
    question: str,
    *,
    dataset: str = BUNDLED_ID,
    allow_llm: bool = False,
    chain: Callable[[], ProviderChain] | None = never_called,
) -> AskResponse:
    target = service.resolve(dataset, settings, UploadStore(settings))
    assert target is not None
    return service.ask(
        AskRequest(dataset=dataset, question=question, allow_llm=allow_llm),
        target,
        settings=settings,
        db=None,
        visitor="v",
        chain_factory=chain,
    )


def test_rules_answer_without_the_model(csv_settings: CsvSettings) -> None:
    r = ask(csv_settings, "Top 3 countries by revenue")
    assert r.status == "answered"
    assert r.interpreter.kind == "rules"
    assert r.interpreter.tokens == 0
    assert len(r.rows) == 3
    assert [c.role for c in r.columns] == ["group", "metric"]
    assert r.sql is not None and "LIMIT ?" not in r.sql  # the display SQL shows the values
    assert r.chart == "bar"
    assert r.summary


def test_bundled_table_falls_back_to_the_model(csv_settings: CsvSettings) -> None:
    calls: list[ChatRequest] = []
    plan = '{"metrics": [{"agg": "avg", "column": "quantity"}]}'
    r = ask(
        csv_settings, "On average how big is a line?", chain=scripted(PLAN_TOOL.name, plan, calls)
    )
    assert r.status == "answered"
    assert r.interpreter.kind == "llm"
    assert r.interpreter.provider == "scripted"
    assert len(calls) == 1


def test_uploads_only_use_the_model_when_allowed(upload_settings: CsvSettings) -> None:
    upload = UploadStore(upload_settings).save(UPLOAD, "league.csv")
    r = ask(upload_settings, "Who won the league?", dataset=upload.id)
    assert r.status == "not_understood"
    assert "allow the LLM fallback" in (r.message or "")
    assert r.suggestions

    calls: list[ChatRequest] = []
    plan = '{"metrics": [{"agg": "sum", "column": "points"}], "group_by": ["team"], "limit": 1}'
    r = ask(
        upload_settings,
        "Who won the league?",
        dataset=upload.id,
        allow_llm=True,
        chain=scripted(PLAN_TOOL.name, plan, calls),
    )
    assert r.status == "answered"
    assert r.rows == [["Red", 3]]
    system = calls[0].messages[0].content or ""
    assert "team (text)" in system
    assert "Red" not in system  # uploads send column names and types, never values


def test_refusal_is_reported(csv_settings: CsvSettings) -> None:
    calls: list[ChatRequest] = []
    r = ask(
        csv_settings,
        "Which product will sell best next Christmas?",
        chain=scripted(REFUSE_TOOL.name, '{"reason": "That is a forecast."}', calls),
    )
    assert r.status == "refused"
    assert r.message == "That is a forecast."
    assert not r.rows


def test_no_model_configured(csv_settings: CsvSettings) -> None:
    r = ask(csv_settings, "Which product will sell best next Christmas?", chain=None)
    assert r.status == "not_understood"
    assert r.interpreter.kind == "none"


def test_query_timeout_is_a_failed_answer(
    monkeypatch: pytest.MonkeyPatch, csv_settings: CsvSettings
) -> None:
    def slow(*_: object, **__: object) -> None:
        raise QueryTimeoutError("interrupted")

    monkeypatch.setattr(service, "run_query", slow)
    r = ask(csv_settings, "Revenue per month")
    assert r.status == "failed"
    assert "stopped after 5 seconds" in (r.message or "")
    assert r.sql  # the plan is still shown


def test_upload_examples_are_answerable(upload_settings: CsvSettings) -> None:
    upload = UploadStore(upload_settings).save(UPLOAD, "league.csv")
    target = service.resolve(upload.id, upload_settings, UploadStore(upload_settings))
    assert target is not None
    assert target.examples
    for question in target.examples:
        assert ask(upload_settings, question, dataset=upload.id).status == "answered", question


def test_bundled_examples_are_answerable(csv_settings: CsvSettings) -> None:
    target = service.resolve(BUNDLED_ID, csv_settings, UploadStore(csv_settings))
    assert target is not None
    for question in target.examples:
        assert ask(csv_settings, question).status == "answered", question
