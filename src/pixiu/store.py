"""Main Pixiu S3 wrapper client."""

from __future__ import annotations

from datetime import datetime
import io
import json
from pathlib import Path
from typing import Any

import boto3
import pandas as pd
import s3fs
import xarray as xr

from pixiu.cache import CacheRecord, PixiuCache
from pixiu.config import load_config
from pixiu.errors import DownloadModeError, ExternalDependencyError


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

    def get_from_csv(self, key: str, **read_csv_kwargs: Any) -> pd.DataFrame:
        try:
            record = self._record_for_key(key)
            cache_key = self._csv_cache_key(key, read_csv_kwargs)

            cached = self._cache.get(cache_key, record)
            if cached is not None:
                return cached

            obj = self._s3.get_object(Bucket=self.bucket, Key=key)
            dataframe = pd.read_csv(obj["Body"], **read_csv_kwargs)
            self._cache.set(cache_key, record, dataframe)
            return dataframe
        except Exception as exc:  # pragma: no cover - covered via tests with explicit assertion
            self._raise_external_error("read CSV", key, exc)

    def get_from_nc(self, key: str) -> xr.Dataset:
        try:
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
        except Exception as exc:  # pragma: no cover - covered via tests with explicit assertion
            self._raise_external_error("read NetCDF", key, exc)

    def upload(self, local_path: str | Path, key: str) -> None:
        try:
            path = Path(local_path)
            self._s3.upload_file(str(path), self.bucket, key)
        except Exception as exc:  # pragma: no cover - covered via tests with explicit assertion
            self._raise_external_error("upload object", key, exc)

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
            try:
                target = Path(local_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                self._s3.download_file(self.bucket, key, str(target))
                return target
            except Exception as exc:  # pragma: no cover - covered via tests with explicit assertion
                self._raise_external_error("download object", key, exc)

        if prefix is not None and local_dir is not None:
            try:
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
            except Exception as exc:  # pragma: no cover - covered via tests with explicit assertion
                self._raise_external_error("download prefix", prefix, exc)

        raise DownloadModeError(
            "Invalid download arguments. Use key/local_path or prefix/local_dir."
        )

    def clear_cache(self) -> None:
        self._cache.clear()

    def ls(self, prefix: str | None = None) -> tuple[list[str], list[str]]:
        target = self._s3_path(prefix)
        try:
            entries = self._fs.ls(target, detail=True)

            directories: set[str] = set()
            files: set[str] = set()

            for entry in entries:
                name = str(entry.get("name", ""))
                relative = self._relative_to_target(name, target)
                if not relative:
                    continue

                if str(entry.get("type", "")).lower() == "directory":
                    directories.add(relative.rstrip("/"))
                else:
                    files.add(relative.rstrip("/"))

            return sorted(directories), sorted(files)
        except Exception as exc:  # pragma: no cover - covered via tests with explicit assertion
            self._raise_external_error("list objects", prefix or "/", exc)

    def tree(self, prefix: str | None = None) -> list[str]:
        target = self._s3_path(prefix)
        try:
            all_files = self._fs.find(target)

            directory_paths: set[tuple[str, ...]] = set()
            file_paths: set[tuple[str, ...]] = set()

            for path in all_files:
                relative = self._relative_to_target(str(path), target)
                if not relative:
                    continue

                parts = tuple(segment for segment in relative.split("/") if segment)
                if not parts:
                    continue

                file_paths.add(parts)
                for depth in range(1, len(parts)):
                    directory_paths.add(parts[:depth])

            return self._render_tree((), directory_paths, file_paths)
        except Exception as exc:  # pragma: no cover - covered via tests with explicit assertion
            self._raise_external_error("build tree", prefix or "/", exc)

    def mkdir(self, path: str, create_parents: bool = True) -> None:
        target = self._s3_path(path)
        try:
            self._fs.mkdir(target, create_parents=create_parents)
        except Exception as exc:  # pragma: no cover - covered via tests with explicit assertion
            self._raise_external_error("create folder", path, exc)

    def makedirs(self, path: str, exist_ok: bool = False) -> None:
        target = self._s3_path(path)
        try:
            self._fs.makedirs(target, exist_ok=exist_ok)
        except Exception as exc:  # pragma: no cover - covered via tests with explicit assertion
            self._raise_external_error("create folder tree", path, exc)

    def _resolve_bucket(self, alias_or_bucket: str) -> str:
        return self._config.buckets.get(alias_or_bucket, alias_or_bucket)

    def _normalize_prefix(self, prefix: str | None) -> str:
        if not prefix:
            return ""

        normalized = prefix.strip("/")
        if not normalized:
            return ""
        return f"{normalized}/"

    def _s3_path(self, prefix: str | None) -> str:
        normalized_prefix = self._normalize_prefix(prefix).rstrip("/")
        if not normalized_prefix:
            return self.bucket
        return f"{self.bucket}/{normalized_prefix}"

    def _relative_to_target(self, path: str, target: str) -> str:
        clean_path = self._strip_s3_protocol(path).strip("/")
        clean_target = self._strip_s3_protocol(target).strip("/")

        if clean_path == clean_target:
            return ""
        if clean_path.startswith(f"{clean_target}/"):
            return clean_path[len(clean_target) + 1 :]
        return clean_path.split("/")[-1]

    def _strip_s3_protocol(self, value: str) -> str:
        if value.startswith("s3://"):
            return value[5:]
        return value

    def _csv_cache_key(self, key: str, read_csv_kwargs: dict[str, Any]) -> str:
        if not read_csv_kwargs:
            return f"csv:{self.bucket}:{key}"

        try:
            fingerprint = json.dumps(read_csv_kwargs, sort_keys=True, default=str)
        except TypeError:
            fingerprint = repr(sorted(read_csv_kwargs.items(), key=lambda item: item[0]))
        return f"csv:{self.bucket}:{key}:{fingerprint}"

    def _raise_external_error(self, operation: str, target: str, exc: Exception) -> None:
        raise ExternalDependencyError(
            f"Could not {operation} '{target}' in bucket '{self.bucket}': {type(exc).__name__}: {exc}"
        ) from exc

    def _render_tree(
        self,
        node: tuple[str, ...],
        directory_paths: set[tuple[str, ...]],
        file_paths: set[tuple[str, ...]],
        prefix: str = "",
    ) -> list[str]:
        dir_children = sorted(
            {
                path[len(node)]
                for path in directory_paths
                if len(path) == len(node) + 1 and path[: len(node)] == node
            }
        )
        file_children = sorted(
            {
                path[len(node)]
                for path in file_paths
                if len(path) == len(node) + 1 and path[: len(node)] == node
            }
        )

        entries: list[tuple[str, bool]] = [(name, True) for name in dir_children]
        entries.extend((name, False) for name in file_children)

        lines: list[str] = []
        for index, (name, is_directory) in enumerate(entries):
            is_last = index == len(entries) - 1
            branch = "`-- " if is_last else "|-- "
            suffix = "/" if is_directory else ""
            lines.append(f"{prefix}{branch}{name}{suffix}")

            if is_directory:
                child_prefix = f"{prefix}{'    ' if is_last else '|   '}"
                lines.extend(
                    self._render_tree(
                        node + (name,),
                        directory_paths,
                        file_paths,
                        prefix=child_prefix,
                    )
                )

        return lines

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
