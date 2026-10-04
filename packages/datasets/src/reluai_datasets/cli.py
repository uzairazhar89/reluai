"""``reluai-data``: fetch and verify third-party datasets listed in artifacts/manifest.yaml."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from reluai_core.logging import configure_logging
from reluai_datasets.manifest import load_manifest
from reluai_datasets.materialize import MaterializeError, materialize


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reluai-data", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="download, verify and store a dataset as Parquet")
    fetch.add_argument("dataset_id")
    fetch.add_argument("--out", type=Path, default=Path("data/canonical"))
    fetch.add_argument("--prefer", choices=["canonical", "mirror"], default=None)
    fetch.add_argument("--force", action="store_true")

    sub.add_parser("list", help="list datasets in the manifest")

    args = parser.parse_args(argv)
    configure_logging(level="INFO", json=False)
    manifest = load_manifest()

    if args.command == "list":
        for ds in manifest.datasets:
            print(f"{ds.id:24} {ds.licence.name:12} {ds.title}")
        return 0

    try:
        prov = materialize(
            manifest.get(args.dataset_id), args.out, prefer=args.prefer, force=args.force
        )
    except (KeyError, MaterializeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{prov.dataset_id}: {prov.rows} rows from {prov.source_role} ({prov.source_url})")
    print(f"content sha256 {prov.content_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
