"""Main Pixiu S3 wrapper client."""

from __future__ import annotations

from datetime import datetime
import io
from pathlib import Path
from typing import Any

import boto3
import pandas as pd
import s3fs
import xarray as xr

from pixiu.cache import CacheRecord, PixiuCache
from pixiu.config import load_config
from pixiu.errors import DownloadModeError


class PixiuStore:
    """Small convenience wrapper around Pixiu-compatible S3 storage."""

    def __init__(
        self,
        bucket: str,
        config_path: Path | str | None = None,
        cache_dir: Path | str | None = None,
        max_cache_entries: int = 128,
        s3_client: Any | None = None,
        s3_filesystem: Any | None = None,
    ) -> None:
        self._config = load_config(config_path)
        self.bucket = self._resolve_bucket(bucket)

        self._cache = PixiuCache(
            max_entries=max_cache_entries,
            disk_cache_dir=cache_dir,
        )

        if s3_client is None:
            session = boto3.session.Session()
            self._s3 = session.client(
                "s3",
                endpoint_url=self._config.endpoint_url,
                aws_access_key_id=self._config.access_key,
                aws_secret_access_key=self._config.secret_key,
            )
        else:
            self._s3 = s3_client

        if s3_filesystem is None:
            self._fs = s3fs.S3FileSystem(
                key=self._config.access_key,
                secret=self._config.secret_key,
                client_kwargs={"endpoint_url": self._config.endpoint_url},
            )
        else:
            self._fs = s3_filesystem

    def get_from_csv(self, key: str) -> pd.DataFrame:
        record = self._record_for_key(key)
        cache_key = f"csv:{self.bucket}:{key}"

        cached = self._cache.get(cache_key, record)
        if cached is not None:
            return cached

        obj = self._s3.get_object(Bucket=self.bucket, Key=key)
        dataframe = pd.read_csv(obj["Body"])
        self._cache.set(cache_key, record, dataframe)
        return dataframe

    def get_from_nc(self, key: str) -> xr.Dataset:
        record = self._record_for_key(key)
        cache_key = f"nc:{self.bucket}:{key}"

        cached = self._cache.get(cache_key, record)
        if cached is not None:
            return cached

        obj = self._s3.get_object(Bucket=self.bucket, Key=key)
        binary = obj["Body"].read()
        dataset = xr.open_dataset(io.BytesIO(binary), engine="h5netcdf")
        self._cache.set(cache_key, record, dataset)
        return dataset

    def upload(self, local_path: str | Path, key: str) -> None:
        path = Path(local_path)
        self._s3.upload_file(str(path), self.bucket, key)

    def download(
        self,
        *,
        key: str | None = None,
        local_path: str | Path | None = None,
        prefix: str | None = None,
        local_dir: str | Path | None = None,
    ) -> Path | list[Path]:
        single_mode = key is not None or local_path is not None
        prefix_mode = prefix is not None or local_dir is not None

        if single_mode and prefix_mode:
            raise DownloadModeError(
                "Use either key/local_path or prefix/local_dir, not both."
            )

        if key is not None and local_path is not None:
            target = Path(local_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            self._s3.download_file(self.bucket, key, str(target))
            return target

        if prefix is not None and local_dir is not None:
            destination_dir = Path(local_dir)
            destination_dir.mkdir(parents=True, exist_ok=True)

            downloaded: list[Path] = []
            paginator = self._s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for item in page.get("Contents", []):
                    object_key = item["Key"]
                    relative = object_key[len(prefix) :].lstrip("/")
                    relative = relative or Path(object_key).name
                    target = destination_dir / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    self._s3.download_file(self.bucket, object_key, str(target))
                    downloaded.append(target)
            return downloaded

        raise DownloadModeError(
            "Invalid download arguments. Use key/local_path or prefix/local_dir."
        )

    def clear_cache(self) -> None:
        self._cache.clear()

    def _resolve_bucket(self, alias_or_bucket: str) -> str:
        return self._config.buckets.get(alias_or_bucket, alias_or_bucket)

    def _record_for_key(self, key: str) -> CacheRecord:
        metadata = self._s3.head_object(Bucket=self.bucket, Key=key)
        etag = metadata.get("ETag")
        last_modified = metadata.get("LastModified")

        if isinstance(last_modified, datetime):
            normalized_last_modified = last_modified.isoformat()
        elif last_modified is None:
            normalized_last_modified = None
        else:
            normalized_last_modified = str(last_modified)

        return CacheRecord(etag=str(etag) if etag is not None else None, last_modified=normalized_last_modified)
