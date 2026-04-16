"""Typer CLI for pixiu configuration commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from pixiu.config import (
    DEFAULT_ENDPOINT,
    add_bucket_alias,
    upsert_credentials_and_bucket,
)
from pixiu.errors import PixiuError

app = typer.Typer(no_args_is_help=True, help="Pixiu storage helper CLI.")


@app.command()
def setup(
    endpoint: Annotated[str | None, typer.Option("--endpoint", help="S3 endpoint URL")] = None,
    access_key: Annotated[str | None, typer.Option("--access-key", help="Pixiu access key")] = None,
    secret_key: Annotated[
        str | None,
        typer.Option("--secret-key", help="Pixiu secret key"),
    ] = None,
    alias: Annotated[str | None, typer.Option("--alias", help="Bucket alias")] = None,
    bucket: Annotated[str | None, typer.Option("--bucket", help="Real bucket name")] = None,
    config_path: Annotated[
        Path | None,
        typer.Option("--config-path", hidden=True),
    ] = None,
) -> None:
    """Create or update local pixiu credentials and first bucket alias mapping."""
    endpoint = endpoint or typer.prompt("Endpoint URL", default=DEFAULT_ENDPOINT)
    access_key = access_key or typer.prompt("Access key")
    secret_key = secret_key or typer.prompt("Secret key", hide_input=True)
    alias = alias or typer.prompt("Bucket alias")
    bucket = bucket or typer.prompt("Bucket name")

    try:
        path = upsert_credentials_and_bucket(
            endpoint_url=endpoint.strip(),
            access_key=access_key.strip(),
            secret_key=secret_key.strip(),
            alias=alias.strip(),
            bucket=bucket.strip(),
            config_path=config_path,
        )
    except PixiuError as exc:
        typer.secho(f"Setup failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    typer.secho(
        f"Configuration saved to {path}. Pixiu is ready to use.",
        fg=typer.colors.GREEN,
    )


@app.command("add-bucket")
def add_bucket(
    alias: Annotated[str, typer.Argument(help="Alias used in code")],
    bucket: Annotated[str, typer.Argument(help="Real Pixiu bucket name")],
    config_path: Annotated[
        Path | None,
        typer.Option("--config-path", hidden=True),
    ] = None,
) -> None:
    """Add a new alias -> bucket mapping to local config."""
    try:
        path = add_bucket_alias(alias=alias.strip(), bucket=bucket.strip(), config_path=config_path)
    except PixiuError as exc:
        typer.secho(f"Could not add bucket: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    typer.secho(f"Added alias '{alias}' to config {path}.", fg=typer.colors.GREEN)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
