"""``reluai-support``: build the order snapshot, try a message, run the scenario suite."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from reluai_core.logging import configure_logging

if TYPE_CHECKING:
    from collections.abc import Callable

    from reluai_core.db import Database
    from reluai_inference.chain import ProviderChain


def _db() -> Database:
    from reluai_core.db import Database
    from reluai_core.settings import get_core_settings

    return Database(get_core_settings(), application_name="reluai-support-cli")


def _chain(provider: str, db: Database) -> Callable[[], ProviderChain]:
    from reluai_inference.chain import ProviderChain
    from reluai_inference.config import build_chain, get_inference_settings
    from reluai_support.agent import scripted_chain, scripted_provider

    if provider == "scripted":
        return scripted_chain
    s = get_inference_settings()
    chain = build_chain(s, db, role="answer")
    if provider == "chain":
        return lambda: ProviderChain([*chain.providers, scripted_provider()], chain.ledger)
    chosen = [p for p in chain.providers if p.name == provider and p.available()]
    if not chosen:
        raise SystemExit(
            f"provider {provider!r} is not configured (set its API key, or enable the local "
            "model); nothing was run"
        )
    # A model run must not silently fall back to the scripted agent.
    return lambda: ProviderChain(chosen, chain.ledger)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reluai-support")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build-data", help="Build the order snapshot from the canonical Parquet")
    b.add_argument("--canonical-dir", type=Path, default=Path("/var/lib/reluai/data/canonical"))
    b.add_argument("--out", type=Path, default=None)
    a = sub.add_parser("ask", help="Run one customer message through the agent")
    a.add_argument("customer_id", type=int)
    a.add_argument("message")
    a.add_argument("--provider", default="scripted")
    e = sub.add_parser("evaluate", help="Run the scenario suite and record the result")
    e.add_argument(
        "--provider",
        default="scripted",
        help="scripted, groq, cerebras, local, or chain (models then scripted)",
    )
    e.add_argument("--only", nargs="*", help="Scenario IDs to run (default: all)")
    e.add_argument("--no-record", action="store_true")
    args = parser.parse_args(argv)
    configure_logging(level="WARNING", json=False)
    logging.getLogger().handlers[:] = [logging.StreamHandler(sys.stderr)]

    from reluai_support.settings import get_support_settings

    settings = get_support_settings()
    if args.cmd == "build-data":
        from reluai_support.orders import build_orders

        print(build_orders(args.canonical_dir, args.out or settings.data_dir))
        return 0

    from reluai_support import service

    db = _db()
    try:
        chain_factory = _chain(args.provider, db)
        if args.cmd == "ask":
            from reluai_support.agent import new_session, run_turn

            rt = service.runtime(db, settings, chain_factory, None)
            session = run_turn(rt, new_session(rt, args.customer_id), args.message)
            print(json.dumps(session.model_dump(mode="json", exclude={"messages"}), indent=2))
            return 0
        from reluai_support.evaluation import run_evaluation
        from reluai_support.scenarios import SCENARIOS

        scenarios = tuple(s for s in SCENARIOS if not args.only or s.id in args.only)
        label = args.provider
        if args.provider not in {"scripted", "chain"}:
            provider = chain_factory().providers[0]
            label = f"{provider.name}:{provider.model}"
        summary = run_evaluation(
            lambda cf: service.runtime(db, settings, cf, None),
            chain_factory,
            label=label,
            scenarios=scenarios,
        )
        if args.provider == "chain":
            summary.label = "chain:" + "+".join(summary.providers)
        blocked = sum(r.provider_errors for r in summary.results)
        if blocked:
            print(
                f"{blocked} steps had no provider available (outage or free-tier limit); the "
                "run measures capacity, not the agent, so it was not recorded.",
                file=sys.stderr,
            )
        elif not args.no_record and not args.only:
            service.record_evaluation(db, summary)
        print(
            json.dumps(
                {k: v for k, v in summary.as_dict().items() if k != "results"}
                | {"failed": [r.id for r in summary.results if not r.passed]},
                indent=2,
            )
        )
        return 0
    finally:
        db.dispose()


if __name__ == "__main__":
    sys.exit(main())
