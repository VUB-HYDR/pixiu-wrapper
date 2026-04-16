"""Configuration helpers for pixiu wrapper."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import platform
import tomllib
from typing import Any

import tomli_w

from pixiu.errors import BucketAliasError, ConfigError

DEFAULT_ENDPOINT = "https://pixiu.vub.be"
DEFAULT_PROFILE = "default"


@dataclass(frozen=True)
class PixiuConfig:
    endpoint_url: str
    access_key: str
    secret_key: str
    buckets: dict[str, str]


def get_config_dir() -> Path:
    return Path.home() / ".pixiu"


def get_config_path(config_path: Path | str | None = None) -> Path:
    if config_path is not None:
        return Path(config_path)
    return get_config_dir() / "config.toml"


def ensure_config_dir(config_path: Path | str | None = None) -> Path:
    path = get_config_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _validate_default_profile(raw: dict[str, Any]) -> dict[str, Any]:
    default = raw.get(DEFAULT_PROFILE)
    if not isinstance(default, dict):
        raise ConfigError("Missing [default] section in config file.")

    required = ["endpoint_url", "access_key", "secret_key", "buckets"]
    missing = [field for field in required if field not in default]
    if missing:
        raise ConfigError(f"Missing keys in [default]: {', '.join(missing)}")

    buckets = default.get("buckets")
    if not isinstance(buckets, dict):
        raise ConfigError("[default.buckets] must be a TOML table of alias=bucket entries.")

    return default


def load_config(config_path: Path | str | None = None) -> PixiuConfig:
    path = get_config_path(config_path)
    if not path.exists():
        raise ConfigError(
            f"Pixiu config not found at {path}. Run `pixiu setup` first."
        )

    try:
        with path.open("rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in config file {path}: {exc}") from exc

    default = _validate_default_profile(raw)

    buckets = default["buckets"]
    clean_buckets = {str(alias): str(bucket) for alias, bucket in buckets.items()}

    return PixiuConfig(
        endpoint_url=str(default["endpoint_url"]),
        access_key=str(default["access_key"]),
        secret_key=str(default["secret_key"]),
        buckets=clean_buckets,
    )


def save_config(config: PixiuConfig, config_path: Path | str | None = None) -> Path:
    path = ensure_config_dir(config_path)
    payload = {
        DEFAULT_PROFILE: {
            "endpoint_url": config.endpoint_url,
            "access_key": config.access_key,
            "secret_key": config.secret_key,
            "buckets": config.buckets,
        }
    }

    with path.open("wb") as f:
        tomli_w.dump(payload, f)

    _set_secure_permissions(path)
    return path


def upsert_credentials_and_bucket(
    endpoint_url: str,
    access_key: str,
    secret_key: str,
    alias: str,
    bucket: str,
    config_path: Path | str | None = None,
) -> Path:
    existing_buckets: dict[str, str] = {}
    try:
        existing = load_config(config_path)
        existing_buckets.update(existing.buckets)
    except ConfigError:
        pass

    existing_buckets[alias] = bucket
    config = PixiuConfig(
        endpoint_url=endpoint_url,
        access_key=access_key,
        secret_key=secret_key,
        buckets=existing_buckets,
    )
    return save_config(config, config_path=config_path)


def add_bucket_alias(
    alias: str,
    bucket: str,
    config_path: Path | str | None = None,
) -> Path:
    config = load_config(config_path)
    if alias in config.buckets:
        raise ConfigError(
            f"Alias '{alias}' already exists for bucket '{config.buckets[alias]}'."
        )

    updated = dict(config.buckets)
    updated[alias] = bucket

    return save_config(
        PixiuConfig(
            endpoint_url=config.endpoint_url,
            access_key=config.access_key,
            secret_key=config.secret_key,
            buckets=updated,
        ),
        config_path=config_path,
    )


def resolve_bucket(alias: str, config_path: Path | str | None = None) -> str:
    config = load_config(config_path)
    bucket = config.buckets.get(alias)
    if bucket is None:
        known_aliases = ", ".join(sorted(config.buckets)) or "<none>"
        raise BucketAliasError(
            f"Unknown bucket alias '{alias}'. Known aliases: {known_aliases}"
        )
    return bucket


def _set_secure_permissions(path: Path) -> None:
    if platform.system().lower().startswith("win"):
        return

    try:
        path.chmod(0o600)
    except OSError:
        # Best effort: continue even if filesystem does not support chmod.
        return
