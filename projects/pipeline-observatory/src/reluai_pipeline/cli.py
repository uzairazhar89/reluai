"""``reluai-pipeline``: build sources, run the pipeline from the command line, backfill."""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import json
import socket
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import uvicorn
from fastapi import FastAPI

from reluai_core.cpu_lease import cpu_lease
from reluai_core.db import Database
from reluai_core.errors import install_error_handlers
from reluai_core.logging import configure_logging
from reluai_core.settings import get_core_settings
from reluai_datasets.materialize import Provenance, canonical_paths, load_canonical
from reluai_datasets.online_retail import DATASET_ID
from reluai_pipeline.runner import create_run, execute_run
from reluai_pipeline.scenarios import SCENARIOS
from reluai_pipeline.settings import PipelineSettings, get_pipeline_settings
from reluai_pipeline.sources import crm
from reluai_pipeline.sources.builder import build_sources


@contextmanager
def local_crm_server(settings: PipelineSettings) -> Iterator[str]:
    """Serve the mock CRM on a free localhost port for the duration of the block.

    Used when the API is not running (first deploy, local backfills): the pipeline still
    talks HTTP to the CRM exactly as it does in production. Yields the CRM base URL.
    """
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(crm.router, prefix="/internal/crm")
    app.dependency_overrides[get_pipeline_settings] = lambda: settings
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("local CRM server did not start")
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}/internal/crm"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reluai-pipeline", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("build-sources", help="derive monthly drops, catalogue and CRM register")

    run = sub.add_parser("run", help="run the pipeline once (in this process)")
    run.add_argument("--scenario", choices=sorted(SCENARIOS), default="standard")
    run.add_argument(
        "--local-crm",
        action="store_true",
        help="serve the mock CRM locally instead of calling the API",
    )

    backfill = sub.add_parser("backfill", help="load the next N drops")
    backfill.add_argument("--drops", type=int, default=3)
    backfill.add_argument("--local-crm", action="store_true")

    args = parser.parse_args(argv)
    core = get_core_settings()
    configure_logging(level=core.log_level, json=core.json_logs)
    settings = get_pipeline_settings()

    if args.command == "build-sources":
        df = load_canonical(settings.canonical_dir, DATASET_ID)
        _, prov_path = canonical_paths(settings.canonical_dir, DATASET_ID)
        prov = Provenance.model_validate_json(prov_path.read_text(encoding="utf-8"))
        index = build_sources(df, settings.sources_dir, content_sha256=prov.content_sha256)
        print(
            f"built {len(index.drops)} drops, {index.products} products, "
            f"{index.customers} customers in {settings.sources_dir}"
        )
        return 0

    db = Database(core, application_name="reluai-pipeline-cli")
    runs = [args.scenario] if args.command == "run" else ["standard"] * args.drops
    trigger = "cli" if args.command == "run" else "backfill"
    exit_code = 0
    with contextlib.ExitStack() as stack:
        if args.local_crm:
            url = stack.enter_context(local_crm_server(settings))
            settings = settings.model_copy(update={"crm_base_url": url})
        for scenario in runs:
            run_id = create_run(db, scenario=scenario, trigger=trigger)
            with cpu_lease(
                db.engine,
                holder=f"pipeline-cli:{str(run_id)[:8]}",
                wait_seconds=core.cpu_lease_wait_seconds,
            ):
                outcome = execute_run(db, settings, run_id)
            print(json.dumps(dataclasses.asdict(outcome), default=str))
            if outcome.status != "succeeded" and scenario in {"standard", "replay"}:
                exit_code = 1
    db.dispose()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
