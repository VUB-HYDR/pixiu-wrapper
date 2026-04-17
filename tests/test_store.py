from __future__ import annotations

from datetime import datetime, timezone
import io

import pandas as pd
import pytest

from pixiu.errors import ExternalDependencyError
from pixiu.store import PixiuStore


class FakePaginator:
    def paginate(self, Bucket, Prefix, Delimiter=None):
        if Delimiter == "/":
            return [
                {
                    "CommonPrefixes": [{"Prefix": f"{Prefix}nested/"}],
                    "Contents": [{"Key": f"{Prefix}a.csv"}],
                }
            ]

        return [
            {
                "Contents": [
                    {"Key": f"{Prefix}a.csv"},
                    {"Key": f"{Prefix}nested/b.csv"},
                    {"Key": f"{Prefix}nested/c.csv"},
                ]
            }
        ]


class FakeS3FileSystem:
    def __init__(self):
        self.mkdir_calls = []
        self.makedirs_calls = []
        self.rm_calls = []

    def ls(self, path, detail=True):
        assert detail is True
        if path.endswith("next_folder"):
            return [
                {"name": f"{path}/nested", "type": "directory"},
                {"name": f"{path}/file.csv", "type": "file"},
            ]

        return [
            {"name": f"{path}/nested", "type": "directory"},
            {"name": f"{path}/a.csv", "type": "file"},
        ]

    def find(self, path):
        if path.endswith("next_folder"):
            return [f"{path}/nested/file.csv"]

        return [
            f"{path}/a.csv",
            f"{path}/nested/b.csv",
            f"{path}/nested/c.csv",
        ]

    def mkdir(self, path, create_parents=True):
        self.mkdir_calls.append((path, create_parents))

    def makedirs(self, path, exist_ok=False):
        self.makedirs_calls.append((path, exist_ok))

    def rm(self, path, recursive=False):
        self.rm_calls.append((path, recursive))


class FakeS3Client:
    def __init__(self):
        self.upload_calls = []
        self.download_calls = []
        self.get_object_calls = 0

    def head_object(self, Bucket, Key):
        return {"ETag": '"etag1"', "LastModified": datetime(2024, 1, 1, tzinfo=timezone.utc)}

    def get_object(self, Bucket, Key):
        self.get_object_calls += 1
        if Key == "swap.csv":
            return {
                "Body": io.BytesIO(
                    b"* Project: hupsel\n"
                    b"* File content: specified output data of SWAP\n"
                    b"DATETIME,RAIN\n"
                    b"2002-01-31,4.26\n"
                )
            }
        if Key.endswith(".csv"):
            return {"Body": io.BytesIO(b"a,b\n1,2\n")}
        return {"Body": io.BytesIO(b"mock_nc")}

    def upload_file(self, Filename, Bucket, Key):
        self.upload_calls.append((Filename, Bucket, Key))

    def download_file(self, Bucket, Key, Filename):
        self.download_calls.append((Bucket, Key, Filename))
        with open(Filename, "wb") as f:
            f.write(b"downloaded")

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return FakePaginator()


def write_config(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
[default]
endpoint_url = "https://pixiu.vub.be"
access_key = "abc"
secret_key = "def"

[default.buckets]
project1 = "hydr-bgw-project1"
""".strip()
    )


def test_get_from_csv_uses_cache(tmp_path):
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    s3 = FakeS3Client()
    store = PixiuStore("project1", config_path=config_path, s3_client=s3, s3_filesystem=object())

    first = store.get_from_csv("data.csv")
    second = store.get_from_csv("data.csv")

    assert isinstance(first, pd.DataFrame)
    assert first.equals(second)
    assert s3.get_object_calls == 1


def test_get_from_csv_forwards_read_csv_kwargs(tmp_path):
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    s3 = FakeS3Client()
    store = PixiuStore("project1", config_path=config_path, s3_client=s3, s3_filesystem=object())

    dataframe = store.get_from_csv("swap.csv", comment="*")

    assert list(dataframe.columns) == ["DATETIME", "RAIN"]
    assert dataframe.iloc[0]["RAIN"] == 4.26


def test_upload_and_download_modes(tmp_path):
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    s3 = FakeS3Client()
    store = PixiuStore("project1", config_path=config_path, s3_client=s3, s3_filesystem=object())

    source = tmp_path / "in.txt"
    source.write_text("payload", encoding="utf-8")

    store.upload(source, "uploads/in.txt")
    assert s3.upload_calls

    single_target = tmp_path / "single" / "out.txt"
    result = store.download(key="uploads/in.txt", local_path=single_target)
    assert result == single_target
    assert single_target.exists()

    many = store.download(prefix="uploads/", local_dir=tmp_path / "many")
    assert len(many) == 3
    assert all(path.exists() for path in many)


def test_get_from_nc_is_cacheable(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    s3 = FakeS3Client()
    store = PixiuStore("project1", config_path=config_path, s3_client=s3, s3_filesystem=object())

    open_calls = {"count": 0}

    def fake_open_dataset(*args, **kwargs):
        open_calls["count"] += 1
        return {"ok": True}

    monkeypatch.setattr("pixiu.store.xr.open_dataset", fake_open_dataset)

    first = store.get_from_nc("field.nc")
    second = store.get_from_nc("field.nc")

    assert first == {"ok": True}
    assert second == {"ok": True}
    assert open_calls["count"] == 1


def test_ls_and_tree(tmp_path):
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    s3 = FakeS3Client()
    fs = FakeS3FileSystem()
    store = PixiuStore("project1", config_path=config_path, s3_client=s3, s3_filesystem=fs)

    directories, files = store.ls()
    assert directories == ["nested"]
    assert files == ["a.csv"]

    tree_lines = store.tree()
    assert tree_lines == [
        "|-- nested/",
        "|   |-- b.csv",
        "|   `-- c.csv",
        "`-- a.csv",
    ]

    nested_directories, nested_files = store.ls("next_folder")
    assert nested_directories == ["nested"]
    assert nested_files == ["file.csv"]

    nested_tree = store.tree("next_folder")
    assert nested_tree == [
        "`-- nested/",
        "    `-- file.csv",
    ]


def test_folder_creation_wrappers(tmp_path):
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    s3 = FakeS3Client()
    fs = FakeS3FileSystem()
    store = PixiuStore("project1", config_path=config_path, s3_client=s3, s3_filesystem=fs)

    store.mkdir("runs/2026", create_parents=False)
    store.makedirs("runs/2026/04", exist_ok=True)

    assert fs.mkdir_calls == [("hydr-bgw-project1/runs/2026", False)]
    assert fs.makedirs_calls == [("hydr-bgw-project1/runs/2026/04", True)]


def test_delete_wrappers(tmp_path):
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    s3 = FakeS3Client()
    fs = FakeS3FileSystem()
    store = PixiuStore("project1", config_path=config_path, s3_client=s3, s3_filesystem=fs)

    store.rm("uploads/one.csv")
    store.rm("uploads/folder", recursive=True)
    store.purge("uploads/folder2")

    assert fs.rm_calls == [
        ("hydr-bgw-project1/uploads/one.csv", False),
        ("hydr-bgw-project1/uploads/folder", True),
        ("hydr-bgw-project1/uploads/folder2", True),
    ]


def test_get_from_csv_wraps_external_errors(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    s3 = FakeS3Client()
    store = PixiuStore("project1", config_path=config_path, s3_client=s3, s3_filesystem=object())

    def fail_read_csv(*args, **kwargs):
        raise ValueError("bad csv")

    monkeypatch.setattr("pixiu.store.pd.read_csv", fail_read_csv)

    with pytest.raises(ExternalDependencyError) as exc_info:
        store.get_from_csv("data.csv")

    assert "Could not read CSV 'data.csv'" in str(exc_info.value)
    assert "ValueError: bad csv" in str(exc_info.value)


def test_ls_wraps_external_errors(tmp_path):
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    s3 = FakeS3Client()

    class FailingFs:
        def ls(self, path, detail=True):
            raise RuntimeError("s3fs unavailable")

    store = PixiuStore("project1", config_path=config_path, s3_client=s3, s3_filesystem=FailingFs())

    with pytest.raises(ExternalDependencyError) as exc_info:
        store.ls()

    assert "Could not list objects '/'" in str(exc_info.value)
    assert "RuntimeError: s3fs unavailable" in str(exc_info.value)


def test_mkdir_wraps_external_errors(tmp_path):
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    s3 = FakeS3Client()

    class FailingFs:
        def mkdir(self, path, create_parents=True):
            raise RuntimeError("mkdir failed")

        def makedirs(self, path, exist_ok=False):
            raise RuntimeError("makedirs failed")

    store = PixiuStore("project1", config_path=config_path, s3_client=s3, s3_filesystem=FailingFs())

    with pytest.raises(ExternalDependencyError) as mkdir_exc:
        store.mkdir("new-folder")

    assert "Could not create folder 'new-folder'" in str(mkdir_exc.value)
    assert "RuntimeError: mkdir failed" in str(mkdir_exc.value)

    with pytest.raises(ExternalDependencyError) as makedirs_exc:
        store.makedirs("a/b/c")

    assert "Could not create folder tree 'a/b/c'" in str(makedirs_exc.value)
    assert "RuntimeError: makedirs failed" in str(makedirs_exc.value)


def test_rm_and_purge_wrap_external_errors(tmp_path):
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    s3 = FakeS3Client()

    class FailingFs:
        def rm(self, path, recursive=False):
            if recursive:
                raise RuntimeError("purge failed")
            raise RuntimeError("rm failed")

    store = PixiuStore("project1", config_path=config_path, s3_client=s3, s3_filesystem=FailingFs())

    with pytest.raises(ExternalDependencyError) as rm_exc:
        store.rm("one.csv")

    assert "Could not remove object(s) 'one.csv'" in str(rm_exc.value)
    assert "RuntimeError: rm failed" in str(rm_exc.value)

    with pytest.raises(ExternalDependencyError) as purge_exc:
        store.purge("folder")

    assert "Could not purge folder 'folder'" in str(purge_exc.value)
    assert "RuntimeError: purge failed" in str(purge_exc.value)
