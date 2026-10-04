#!/usr/bin/env python3
"""Fail if retired brand names or legacy artefacts reappear in the repository or build output.

Run in CI on the source tree and again on the built web output (`apps/web/.next`).
Usage: python scripts/check_denylist.py [PATH ...]   (defaults to the repository root)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Terms that must never appear again (case-insensitive). Built from fragments so this file
# does not match itself.
DENY = [
    re.compile("zar" + "wa", re.IGNORECASE),
]
SKIP_DIRS = {".git", "node_modules", ".venv", ".mypy_cache", ".ruff_cache", ".pytest_cache", "data"}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".avif", ".ico", ".woff2", ".gz", ".parquet"}
SELF = Path(__file__).resolve()
# The only file allowed to name the retired URL path: it exists to answer it with 410 Gone.
ALLOW_FILES = {Path("infra/nginx/snippets/legacy-routes.conf")}
REPO_ROOT = SELF.parent.parent


def _allowed(path: Path) -> bool:
    try:
        return path.resolve().relative_to(REPO_ROOT) in ALLOW_FILES
    except ValueError:
        return False


def scan(root: Path) -> list[str]:
    hits: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.resolve() == SELF or _allowed(path):
            continue
        if any(part in SKIP_DIRS for part in path.parts) or path.suffix in SKIP_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if any(p.search(line) for p in DENY):
                hits.append(f"{path}:{lineno}")
        if any(p.search(path.name) for p in DENY):
            hits.append(f"{path} (file name)")
    return hits


def main(argv: list[str]) -> int:
    roots = [Path(a) for a in argv] or [Path(__file__).resolve().parent.parent]
    hits = [h for r in roots for h in scan(r)]
    if hits:
        print("Denylisted term found:", *hits, sep="\n  ")
        return 1
    print(f"Denylist check passed ({', '.join(str(r) for r in roots)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
