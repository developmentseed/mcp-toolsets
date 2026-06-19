"""Semantic search over EQC prose (local model2vec, no LLM API)."""

from __future__ import annotations

import argparse
import json
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
from model2vec import StaticModel

from cds.eqc.normalize import prose_from_markdown
from cds.eqc.paths import default_data_dir, default_index_dir

MODEL_NAME = "minishlab/potion-retrieval-32M"


@lru_cache(maxsize=2)
def get_model(local_dir: str | None = None) -> StaticModel:
    return StaticModel.from_pretrained(local_dir or MODEL_NAME, quantize_to="int8")


def _index_model(index_dir: Path) -> StaticModel:
    bundled = index_dir / "model"
    return get_model(str(bundled)) if bundled.is_dir() else get_model()


def normalize(v: np.ndarray) -> np.ndarray:
    return v / np.clip(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12, None)


def _portable_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _resolve_data_dir(raw: str, default: Path) -> Path:
    data_dir = Path(raw)
    if not data_dir.is_absolute():
        data_dir = default.parent / data_dir
    if not data_dir.exists():
        data_dir = default
    return data_dir


def data_status(
    data_dir: Path | None = None,
    index_dir: Path | None = None,
    min_datasets: int = 1,
) -> tuple[bool, str]:
    data_dir = data_dir or default_data_dir()
    index_dir = index_dir or default_index_dir()
    index_json = data_dir / "index.json"
    if not index_json.exists():
        return False, f"missing EQC corpus at {data_dir}"
    n_eqc = sum(
        1
        for d in json.loads(index_json.read_text(encoding="utf-8")).get("datasets", [])
        if d.get("has_eqc")
    )
    if n_eqc < min_datasets:
        return False, (
            f"corpus at {data_dir} has {n_eqc} EQC datasets "
            f"(expected >= {min_datasets})"
        )
    for name in ("embeddings.npy", "meta.jsonl", "config.json"):
        if not (index_dir / name).exists():
            return False, f"missing sgrep index file {index_dir / name}"
    n_chunks = np.load(index_dir / "embeddings.npy", mmap_mode="r").shape[0]
    n_meta = sum(
        1
        for line in (index_dir / "meta.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    )
    if n_chunks != n_meta:
        return False, (
            f"sgrep index inconsistent: {n_chunks} embeddings "
            f"vs {n_meta} meta entries in {index_dir}"
        )
    return True, (
        f"{n_eqc} EQC datasets in {data_dir}, "
        f"{n_chunks} indexed prose documents in {index_dir}"
    )


def build_index(
    data_dir: Path | None = None,
    index_dir: Path | None = None,
) -> None:
    data_dir = (data_dir or default_data_dir()).resolve()
    index_dir = (index_dir or default_index_dir()).resolve()
    root = data_dir.parent

    meta, texts = [], []
    for path in sorted(data_dir.glob("*.md")):
        prose = prose_from_markdown(path.read_text(encoding="utf-8"))
        if not prose:
            continue
        meta.append({"file": str(path.relative_to(data_dir))})
        texts.append(prose)

    if not texts:
        raise RuntimeError(f"no EQC prose found in {data_dir}")

    model = get_model()
    emb = normalize(model.encode(texts)).astype("float32")
    scale = float(np.abs(emb).max() / 127.0) or 1.0
    q8 = np.round(emb / scale).clip(-127, 127).astype(np.int8)

    index_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(index_dir / "model")
    np.save(index_dir / "embeddings.npy", q8)
    (index_dir / "config.json").write_text(
        json.dumps(
            {
                "scale": scale,
                "dim": int(emb.shape[1]),
                "data_dir": _portable_path(data_dir, root),
            }
        ),
        encoding="utf-8",
    )
    (index_dir / "meta.jsonl").write_text(
        "\n".join(json.dumps(m, ensure_ascii=False) for m in meta),
        encoding="utf-8",
    )


@lru_cache(maxsize=64)
def _file_prose(path_str: str) -> str:
    return prose_from_markdown(Path(path_str).read_text(encoding="utf-8"))


@lru_cache(maxsize=4)
def _load_index(index_dir_str: str) -> tuple[np.ndarray, list[dict], float, Path]:
    index_dir = Path(index_dir_str)
    default = default_data_dir()
    emb = np.load(index_dir / "embeddings.npy").astype("float32")
    config = json.loads((index_dir / "config.json").read_text(encoding="utf-8"))
    meta = [
        json.loads(line)
        for line in (index_dir / "meta.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    return emb, meta, config["scale"], _resolve_data_dir(config["data_dir"], default)


def query_index(
    query: str,
    *,
    index_dir: Path | None = None,
    k: int = 10,
    threshold: float = 0.08,
) -> list[dict]:
    index_dir = (index_dir or default_index_dir()).resolve()
    emb, meta, scale, data_dir = _load_index(str(index_dir))
    qv = normalize(_index_model(index_dir).encode([query])[0]).astype("float32")
    scores = (emb @ qv) * scale

    results = []
    for i in np.argsort(-scores)[:k]:
        if scores[i] < threshold:
            break
        m = meta[i]
        dataset_id = Path(m["file"]).stem
        results.append(
            {
                "dataset_id": dataset_id,
                "score": float(scores[i]),
                "text": _file_prose(str(data_dir / m["file"])),
                "source_url": (
                    f"https://cds.climate.copernicus.eu/datasets/{dataset_id}"
                    "?tab=quality_assurance_tab"
                ),
            }
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(prog="cds-eqc-sgrep", description="EQC semantic grep")
    sub = parser.add_subparsers(dest="cmd")

    idx = sub.add_parser("index", help="build the search index")
    idx.add_argument("--data", type=Path, default=None)
    idx.add_argument("--index", type=Path, default=None)

    srch = sub.add_parser("search", help="search the index")
    srch.add_argument("query")
    srch.add_argument("--index", type=Path, default=None)
    srch.add_argument("--top", type=int, default=10)
    srch.add_argument("--threshold", type=float, default=0.08)

    if len(sys.argv) > 1 and sys.argv[1] not in ("index", "search", "-h", "--help"):
        sys.argv.insert(1, "search")

    args = parser.parse_args()
    if args.cmd == "index":
        build_index(args.data, args.index)
    elif args.cmd == "search":
        for r in query_index(
            args.query,
            index_dir=args.index,
            k=args.top,
            threshold=args.threshold,
        ):
            print(f"{r['dataset_id']} ({r['score']:.2f}): {r['text'][:120]}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
