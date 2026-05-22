"""bizpulse CLI entrypoint (stub)."""

from __future__ import annotations

import typer

from bizpulse import __version__
from bizpulse.config import settings
from bizpulse.logging import configure, get_logger

app = typer.Typer(no_args_is_help=True, add_completion=False)
log = get_logger(__name__)


@app.callback()
def _root() -> None:
    """BizPulse CLI."""
    configure(settings.log_level)


@app.command()
def version() -> None:
    """Print bizpulse version."""
    typer.echo(__version__)


@app.command()
def info() -> None:
    """Print effective settings (secrets redacted)."""
    redact = {
        "postgres_password",
        "llm_api_key",
        "anthropic_api_key",
        "tavily_api_key",
        "brave_search_api_key",
        "qdrant_api_key",
    }
    for k, v in settings.model_dump().items():
        shown = "***" if k in redact and v else v
        typer.echo(f"{k:<22} {shown}")


if __name__ == "__main__":
    app()
