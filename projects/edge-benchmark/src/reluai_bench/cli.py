"""``reluai-bench``: build the models, run the benchmark, classify a photo."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from reluai_bench.settings import get_bench_settings


def _table(run: dict) -> str:  # type: ignore[type-arg]
    lines = [f"{'model':18} {'variant':13} thr {'p50 ms':>8} {'p95 ms':>8} {'infer':>7} "
             f"{'img/s':>7} {'cpu%':>5} {'peak MB':>8} {'size MB':>8}"]  # fmt: skip
    for r in run["results"]:
        lat = r["latency_ms"]
        lines.append(
            f"{r['model']:18} {r['variant']:13} {r['threads']:>3} {lat['total']['p50']:8.2f} "
            f"{lat['total']['p95']:8.2f} {lat['inference']['p50']:7.2f} "
            f"{r['throughput']['images_per_second']:7.1f} {r['cpu_percent']:5.0f} "
            f"{r['memory_mb']['peak']:8.0f} {r['size_bytes'] / 1e6:8.1f}"
        )
    lines.extend(
        f"{a['model']:18} {a['variant']:13} vs {a['reference']}: top-1 same "
        f"{a['top1_agreement']}%, top-5 overlap {a['top5_overlap']}%, "
        f"max |Δp| {a['max_probability_difference']:.2e} ({a['photos']} photos)"
        for a in run["agreement"]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reluai-bench", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="Fetch weights and photos, export and quantise (image build)")
    b.add_argument("--out", type=Path, default=None, help="data dir (default: settings)")
    b.add_argument("--bundle", type=Path, default=None, help="local coco-cc bundle tar")
    b.add_argument(
        "--photos", type=Path, default=None, help="development only: a folder of JPEG photos"
    )
    b.add_argument("--method", default=None, help="calibration method (MinMax, Entropy, ...)")
    r = sub.add_parser("run", help="Run the benchmark suite on this machine")
    r.add_argument("--model", action="append", default=None)
    r.add_argument("--threads", type=int, action="append", default=None)
    r.add_argument("--iterations", type=int, default=None)
    r.add_argument("--record", action="store_true", help="store the run in the database")
    r.add_argument("--json", type=Path, default=None, help="also write the run to this file")
    c = sub.add_parser("classify", help="Run one photo through every variant of a model")
    c.add_argument("photo", type=Path)
    c.add_argument("--model", default="mobilenetv3-small")
    args = parser.parse_args(argv)
    settings = get_bench_settings()

    if args.cmd == "build":
        from reluai_bench.build import CALIBRATION_METHOD, build

        reg = build(
            args.out or settings.data_dir,
            torch_python=settings.torch_python,
            bundle=args.bundle,
            photo_dir=args.photos,
            method=args.method or CALIBRATION_METHOD,
        )
        print(json.dumps({k: reg[k] for k in ("tools", "quantisation", "photos")}, indent=1))
        return 0

    if args.cmd == "run":
        from reluai_bench.benchmark import run_suite

        if args.iterations:
            settings = settings.model_copy(update={"iterations": args.iterations})
        run = run_suite(
            settings,
            models=args.model,
            threads=tuple(args.threads) if args.threads else None,
            progress=lambda msg: print(f"… {msg}", file=sys.stderr),
        )
        print(_table(run))
        hw = run["hardware"]
        print(f"hardware {hw['id']}: {hw['cpu']['model']}, {hw['usable_cpus']} CPUs, "
              f"{' '.join(hw['cpu']['flags'])}; {run['duration_seconds']} s")  # fmt: skip
        if args.json:
            args.json.write_text(json.dumps(run, indent=1), encoding="utf-8")
        if args.record:
            from reluai_bench.service import record_run
            from reluai_core.db import Database
            from reluai_core.settings import get_core_settings

            db = Database(get_core_settings(), application_name="reluai-bench-cli")
            try:
                record_run(db, run, label="manual")
            finally:
                db.dispose()
        return 0

    if args.cmd == "classify":
        from reluai_bench.service import classify_bytes

        out = classify_bytes(settings, args.photo.read_bytes(), args.model)
        print(json.dumps(out, indent=1))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
