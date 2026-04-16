from __future__ import annotations

import tomllib

from pixiu.config import PixiuConfig, add_bucket_alias, load_config, save_config
from pixiu.errors import ConfigError


def test_save_and_load_config_roundtrip(tmp_path):
    config_path = tmp_path / "config.toml"
    config = PixiuConfig(
        endpoint_url="https://pixiu.vub.be",
        access_key="abc",
        secret_key="def",
        buckets={"project1": "hydr-bgw-project1"},
    )

    save_config(config, config_path=config_path)
    loaded = load_config(config_path=config_path)

    assert loaded.endpoint_url == "https://pixiu.vub.be"
    assert loaded.access_key == "abc"
    assert loaded.secret_key == "def"
    assert loaded.buckets["project1"] == "hydr-bgw-project1"


def test_add_bucket_alias_updates_config(tmp_path):
    config_path = tmp_path / "config.toml"
    config = PixiuConfig(
        endpoint_url="https://pixiu.vub.be",
        access_key="abc",
        secret_key="def",
        buckets={"project1": "hydr-bgw-project1"},
    )
    save_config(config, config_path=config_path)

    add_bucket_alias("project2", "hydr-bgw-project2", config_path=config_path)

    loaded = load_config(config_path=config_path)
    assert loaded.buckets["project1"] == "hydr-bgw-project1"
    assert loaded.buckets["project2"] == "hydr-bgw-project2"


def test_add_bucket_alias_rejects_duplicates(tmp_path):
    config_path = tmp_path / "config.toml"
    config = PixiuConfig(
        endpoint_url="https://pixiu.vub.be",
        access_key="abc",
        secret_key="def",
        buckets={"project1": "hydr-bgw-project1"},
    )
    save_config(config, config_path=config_path)

    try:
        add_bucket_alias("project1", "hydr-bgw-project-new", config_path=config_path)
    except ConfigError:
        pass
    else:
        raise AssertionError("Expected ConfigError for duplicate alias")


def test_config_uses_default_buckets_table_shape(tmp_path):
    config_path = tmp_path / "config.toml"
    config = PixiuConfig(
        endpoint_url="https://pixiu.vub.be",
        access_key="abc",
        secret_key="def",
        buckets={"project1": "hydr-bgw-project1"},
    )
    save_config(config, config_path=config_path)

    with config_path.open("rb") as f:
        payload = tomllib.load(f)

    assert "default" in payload
    assert "buckets" in payload["default"]
    assert payload["default"]["buckets"]["project1"] == "hydr-bgw-project1"
