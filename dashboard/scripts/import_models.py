from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def weight_path(directory: Path) -> Path:
    for name in ("model.safetensors", "pytorch_model.bin"):
        path = directory / name
        if path.is_file():
            return path
    raise SystemExit(f"No model weight file in {directory}")


def checked_copy(source: Path, destination: Path, expected: str) -> None:
    weight = weight_path(source)
    if sha256(weight) != expected:
        raise SystemExit(f"Weight checksum mismatch: {weight}")
    if destination.exists():
        raise SystemExit(f"Destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy the two optional live models into the dashboard")
    parser.add_argument("--byt5-source", type=Path)
    parser.add_argument("--spert-source", type=Path)
    parser.add_argument("--types-source", type=Path)
    args = parser.parse_args()
    manifest = json.loads((ROOT / "models" / "manifest.json").read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in manifest["optional_live_models"]}
    copied = []
    if args.byt5_source:
        item = by_id["byt5_gold_checkpoint_1953"]
        checked_copy(args.byt5_source.resolve(), ROOT / item["destination"], item["weight_sha256"])
        copied.append(item["id"])
    if args.spert_source:
        item = by_id["selective_byt5_spert_final"]
        checked_copy(args.spert_source.resolve(), ROOT / item["destination"], item["weight_sha256"])
        if not args.types_source or not args.types_source.is_file():
            raise SystemExit("--types-source is required with --spert-source")
        if sha256(args.types_source) != item["types_sha256"]:
            raise SystemExit("SpERT types checksum mismatch")
        target = ROOT / item["types_destination"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.types_source, target)
        copied.append(item["id"])
    print(json.dumps({"copied": copied, "note": "The default frozen_artifacts profile does not load these weights."}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

