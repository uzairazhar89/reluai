"""``reluai-csv``: build the bundled dataset, try questions, run the evaluation."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from reluai_core.logging import configure_logging
from reluai_csv.settings import get_csv_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reluai-csv", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-dataset", help="build the bundled DuckDB table and profile")
    build.add_argument("--canonical-dir", type=Path)
    build.add_argument("--out", type=Path)
    ask = sub.add_parser("ask", help="interpret and answer a question (rules only)")
    ask.add_argument("question")
    evaluate = sub.add_parser("evaluate", help="run the fixed question set and record the result")
    evaluate.add_argument("--no-record", action="store_true", help="print only")
    args = parser.parse_args(argv)
    settings = get_csv_settings()
    configure_logging(level="INFO", json=False)
    logging.getLogger().handlers[0].setStream(sys.stderr)  # type: ignore[attr-defined]

    if args.command == "build-dataset":
        from reluai_csv.datasets import build_bundled

        target = build_bundled(
            args.canonical_dir or settings.canonical_dir, args.out or settings.data_dir
        )
        print(f"built {target}")
        return 0

    if args.command == "ask":
        from reluai_csv.service import answer_with_rules

        result = answer_with_rules(args.question, settings)
        print(json.dumps(result, indent=2, default=str))
        return 0

    if args.command == "evaluate":
        from reluai_csv.evaluation import run_evaluation

        summary = run_evaluation(settings, record=not args.no_record)
        print(json.dumps(summary, indent=2, default=str))
        return 0 if summary["wrong"] == 0 else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
