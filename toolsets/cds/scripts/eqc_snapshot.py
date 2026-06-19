#!/usr/bin/env python3
"""Pull/push the CDS EQC corpus + sgrep index as a single S3 tarball.

Snapshot layout at ``$CDS_EQC_S3_URI`` (e.g. ``s3://bucket/cds-eqc/``):

    <prefix>/latest.tar.gz     current snapshot (consumed by Docker builds)
    <prefix>/<YYYY.MM.DD>.tar.gz  dated archive

The tarball bundles ``eqc/`` and ``eqc_index/`` under ``data/`` so it extracts
into the CDS toolset data root.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import tarfile
import time
from urllib.parse import urlparse

import boto3

from cds.eqc.paths import default_data_dir, default_index_dir

_DATA_ROOT = default_data_dir().parent
_PAYLOAD_DIRS = (default_data_dir(), default_index_dir())
_LATEST_KEY = "latest.tar.gz"
_ENV_VAR = "CDS_EQC_S3_URI"


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"not an s3:// URI: {uri!r}")
    return parsed.netloc, parsed.path.strip("/")


def _key(prefix: str, name: str) -> str:
    return f"{prefix}/{name}" if prefix else name


def pull() -> int:
    uri = os.environ.get(_ENV_VAR, "").strip()
    if not uri:
        print(f"{_ENV_VAR} not set; skipping pull (local build).")
        return 0

    bucket, prefix = _parse_s3_uri(uri)
    key = _key(prefix, _LATEST_KEY)
    client = boto3.client("s3")
    try:
        obj = client.get_object(Bucket=bucket, Key=key)
    except client.exceptions.NoSuchKey:
        print(f"No snapshot at s3://{bucket}/{key}; nothing to seed.")
        return 0

    _DATA_ROOT.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(obj["Body"].read()), mode="r:gz") as tar:
        tar.extractall(_DATA_ROOT)
    print(f"Extracted s3://{bucket}/{key} into {_DATA_ROOT}")
    return 0


def push() -> int:
    uri = os.environ.get(_ENV_VAR, "").strip()
    if not uri:
        print(f"{_ENV_VAR} not set; cannot push.", file=sys.stderr)
        return 1

    for path in _PAYLOAD_DIRS:
        if not path.exists():
            print(f"Missing payload dir {path}; run fetch_eqc_corpus.py first.", file=sys.stderr)
            return 1

    bucket, prefix = _parse_s3_uri(uri)
    client = boto3.client("s3")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in _PAYLOAD_DIRS:
            tar.add(path, arcname=f"data/{path.name}")
    payload = buf.getvalue()

    latest_key = _key(prefix, _LATEST_KEY)
    client.put_object(Bucket=bucket, Key=latest_key, Body=payload)
    print(f"Uploaded s3://{bucket}/{latest_key} ({len(payload)} bytes)")

    dated = time.strftime("%Y.%m.%d")
    dated_key = _key(prefix, f"{dated}.tar.gz")
    client.put_object(Bucket=bucket, Key=dated_key, Body=payload)
    print(f"Archived s3://{bucket}/{dated_key}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="CDS EQC corpus S3 snapshot")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pull", help="download latest.tar.gz into data/")
    sub.add_parser("push", help="upload data/eqc + data/eqc_index tarball")
    args = parser.parse_args()
    if args.cmd == "pull":
        return pull()
    return push()


if __name__ == "__main__":
    raise SystemExit(main())
