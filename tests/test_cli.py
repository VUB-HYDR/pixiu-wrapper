from __future__ import annotations

from typer.testing import CliRunner

from pixiu.cli import app
from pixiu.config import load_config

runner = CliRunner()


def test_setup_writes_config(tmp_path):
    config_path = tmp_path / "config.toml"

    result = runner.invoke(
        app,
        [
            "setup",
            "--endpoint",
            "https://pixiu.vub.be",
            "--access-key",
            "abc",
            "--secret-key",
            "def",
            "--alias",
            "project1",
            "--bucket",
            "hydr-bgw-project1",
            "--config-path",
            str(config_path),
        ],
    )

    assert result.exit_code == 0, result.stdout
    loaded = load_config(config_path=config_path)
    assert loaded.buckets["project1"] == "hydr-bgw-project1"


def test_add_bucket_positional_command(tmp_path):
    config_path = tmp_path / "config.toml"

    setup_result = runner.invoke(
        app,
        [
            "setup",
            "--endpoint",
            "https://pixiu.vub.be",
            "--access-key",
            "abc",
            "--secret-key",
            "def",
            "--alias",
            "project1",
            "--bucket",
            "hydr-bgw-project1",
            "--config-path",
            str(config_path),
        ],
    )
    assert setup_result.exit_code == 0

    add_result = runner.invoke(
        app,
        ["add-bucket", "project2", "hydr-bgw-project2", "--config-path", str(config_path)],
    )

    assert add_result.exit_code == 0
    loaded = load_config(config_path=config_path)
    assert loaded.buckets["project2"] == "hydr-bgw-project2"
