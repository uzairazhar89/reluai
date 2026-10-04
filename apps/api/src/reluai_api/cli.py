"""``reluai``: operational commands for the API container."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(help="reluai.cloud operations", no_args_is_help=True, add_completion=False)
db_app = typer.Typer(help="Database migrations", no_args_is_help=True)
app.add_typer(db_app, name="db")

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _alembic_config() -> object:
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    return cfg


@db_app.command("migrate")
def migrate(revision: str = "head") -> None:
    """Apply migrations (idempotent; run on every deploy before the API starts)."""
    from alembic import command

    command.upgrade(_alembic_config(), revision)  # type: ignore[arg-type]
    typer.echo(f"database at {revision}")


@db_app.command("current")
def current() -> None:
    from alembic import command

    command.current(_alembic_config(), verbose=False)  # type: ignore[arg-type]


@app.command()
def worker(concurrency: int = 2) -> None:
    """Run the background worker (pipeline runs, scheduled jobs)."""
    from reluai_api.worker import run_worker

    run_worker(concurrency=concurrency)


@app.command()
def openapi(out: Annotated[Path, typer.Option()] = Path("openapi.json")) -> None:
    """Write the OpenAPI document (used to generate the website's typed API client)."""
    from reluai_api.main import create_app
    from reluai_core.settings import CoreSettings

    api = create_app(CoreSettings(expose_api_docs=True))
    out.write_text(json.dumps(api.openapi(), indent=2) + "\n", encoding="utf-8")
    typer.echo(f"wrote {out}")


if __name__ == "__main__":
    app()
