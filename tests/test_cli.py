from __future__ import annotations

from typer.testing import CliRunner

from pixiu.cli import app
from pixiu.config import load_config

runner = CliRunner()


class FakeBrowseStore:
    def __init__(self, bucket, config_path=None):
        self.bucket = bucket
        self.config_path = config_path

    def ls(self, path=None):
        if path == "next_folder":
            return (["nested"], ["file.csv"])
        return (["next_folder"], ["root.csv"])

    def tree(self, path=None):
        if path == "next_folder":
            return ["`-- nested/", "    `-- file.csv"]
        return ["|-- next_folder/", "|   `-- file.csv", "`-- root.csv"]


class FailingBrowseStore:
    def __init__(self, bucket, config_path=None):
        raise RuntimeError("boom")


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


def test_ls_and_tree_commands(monkeypatch):
    monkeypatch.setattr("pixiu.cli.PixiuStore", FakeBrowseStore)

    ls_root = runner.invoke(app, ["ls", "project1"])
    assert ls_root.exit_code == 0
    assert "next_folder/" in ls_root.stdout
    assert "root.csv" in ls_root.stdout

    ls_nested = runner.invoke(app, ["ls", "project1", "next_folder"])
    assert ls_nested.exit_code == 0
    assert "nested/" in ls_nested.stdout
    assert "file.csv" in ls_nested.stdout

    tree_root = runner.invoke(app, ["tree", "project1"])
    assert tree_root.exit_code == 0
    assert tree_root.stdout.splitlines()[0] == "."
    assert "|-- next_folder/" in tree_root.stdout

    tree_nested = runner.invoke(app, ["tree", "project1", "next_folder"])
    assert tree_nested.exit_code == 0
    assert tree_nested.stdout.splitlines()[0] == "next_folder"
    assert "`-- nested/" in tree_nested.stdout


def test_ls_reports_unexpected_errors(monkeypatch):
    monkeypatch.setattr("pixiu.cli.PixiuStore", FailingBrowseStore)

    result = runner.invoke(app, ["ls", "project1"])

    assert result.exit_code == 1
    assert "Browse failed unexpectedly" in result.stderr
    assert "RuntimeError: boom" in result.stderr
