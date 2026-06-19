#!/usr/bin/env python3
"""Fetch CDS EQC snapshots into data/eqc/ and rebuild the semantic index."""

from __future__ import annotations

import argparse
import sys

from cds.eqc.fetch import sync_corpus
from cds.eqc.sgrep import build_index, data_status


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch CDS EQC content and build the local search corpus"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of catalogue datasets to fetch",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch even when sha256 unchanged",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Parallel fetch workers (default 1 for polite rate limiting)",
    )
    parser.add_argument(
        "--skip-index",
        action="store_true",
        help="Only fetch/normalize; do not rebuild sgrep index",
    )
    args = parser.parse_args()

    stats = sync_corpus(limit=args.limit, force=args.force, workers=args.workers)
    print(stats)

    if not args.skip_index and stats.get("eqc_count", 0) > 0:
        build_index()
        ok, detail = data_status(min_datasets=1)
        print(detail)
        if not ok:
            return 1
    elif stats.get("eqc_count", 0) == 0:
        print("No EQC datasets in corpus; skipping index build.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
