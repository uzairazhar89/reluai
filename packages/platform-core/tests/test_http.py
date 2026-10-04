from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from reluai_core.errors import ProblemError, install_error_handlers
from reluai_core.http import BodySizeLimitMiddleware, RequestContextMiddleware


class Item(BaseModel):
    name: str


def make_app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(BodySizeLimitMiddleware, default_limit=64, prefix_limits={"/big": 4096})
    app.add_middleware(RequestContextMiddleware)

    @app.post("/echo")
    def echo(item: Item) -> Item:
        return item

    @app.post("/big/echo")
    def big_echo(item: Item) -> Item:
        return item

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail")

    @app.get("/problem")
    def problem() -> None:
        raise ProblemError(409, "Already running", code="busy", headers={"Retry-After": "5"})

    return app


client = TestClient(make_app(), raise_server_exceptions=False)


def test_request_id_is_generated_and_echoed() -> None:
    r = client.post("/echo", json={"name": "a"})
    assert r.status_code == 200
    assert len(r.headers["x-request-id"]) == 32
    r2 = client.post("/echo", json={"name": "a"}, headers={"X-Request-ID": "abc-123-xyz"})
    assert r2.headers["x-request-id"] == "abc-123-xyz"


def test_invalid_incoming_request_id_is_replaced() -> None:
    r = client.post("/echo", json={"name": "a"}, headers={"X-Request-ID": "bad id!"})
    assert r.headers["x-request-id"] != "bad id!"


def test_body_over_limit_rejected_with_problem_json() -> None:
    r = client.post("/echo", json={"name": "x" * 200})
    assert r.status_code == 413
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["status"] == 413


def test_streamed_body_over_limit_rejected() -> None:
    def gen():  # no Content-Length: chunked upload
        yield b'{"name": "'
        yield b"x" * 200
        yield b'"}'

    r = client.post("/echo", content=gen(), headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_per_prefix_limit_allows_larger_bodies() -> None:
    r = client.post("/big/echo", json={"name": "x" * 200})
    assert r.status_code == 200


def test_unhandled_errors_do_not_leak_details() -> None:
    r = client.get("/boom")
    assert r.status_code == 500
    body = r.json()
    assert "secret" not in r.text
    assert body["code"] == "internal_error"
    assert body["request_id"]


def test_problem_error_maps_status_code_and_headers() -> None:
    r = client.get("/problem")
    assert r.status_code == 409
    assert r.headers["retry-after"] == "5"
    assert r.json()["code"] == "busy"


def test_validation_errors_are_structured() -> None:
    r = client.post("/echo", json={"wrong": 1})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "validation_error"
    assert body["errors"][0]["loc"][-1] == "name"
