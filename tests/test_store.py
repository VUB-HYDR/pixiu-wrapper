from __future__ import annotations

from datetime import datetime, timezone
import io

import pandas as pd

from pixiu.store import PixiuStore


class FakePaginator:
    def paginate(self, Bucket, Prefix):
        return [
            {
                "Contents": [
                    {"Key": f"{Prefix}a.csv"},
                    {"Key": f"{Prefix}nested/b.csv"},
                ]
            }
        ]


class FakeS3Client:
    def __init__(self):
        self.upload_calls = []
        self.download_calls = []
        self.get_object_calls = 0

    def head_object(self, Bucket, Key):
        return {"ETag": '"etag1"', "LastModified": datetime(2024, 1, 1, tzinfo=timezone.utc)}

    def get_object(self, Bucket, Key):
        self.get_object_calls += 1
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
    assert len(many) == 2
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
