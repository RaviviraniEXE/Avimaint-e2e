from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable


SYSTEMS = (
    "raw",
    "most_frequent_replacement",
    "rules",
    "byt5",
    "selective_byt5",
    "rules_then_byt5",
)
EXPECTED_TEST_RECORDS = 741
EXPECTED_VALIDATION_RECORDS = 926
PHASE2_VERSION = "phase2_missing_evidence_final_v1"


def repo_root() -> Path:
    override = os.getenv("AVIMAINT_REPO_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected a JSON object: {path}")
    return value


def atomic_text(path: Path, value: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    os.close(handle)
    temporary = Path(name)
    try:
        temporary.write_text(value, encoding=encoding)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def require_files(paths: Iterable[Path]) -> None:
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise RuntimeError("Required files are missing:\n  - " + "\n  - ".join(missing))


def split_paths(root: Path | None = None) -> tuple[Path, Path]:
    root = root or repo_root()
    return (
        root / "data" / "splits" / "normalization_cluster_safe_v1.csv",
        root / "data" / "splits" / "normalization_cluster_safe_v1.manifest.json",
    )


def prediction_dir(root: Path | None = None) -> Path:
    root = root or repo_root()
    return root / "outputs" / "normalization" / "predictions" / "byt5_gold_v1"


def test_artifacts(root: Path | None = None) -> list[Path]:
    directory = prediction_dir(root)
    result: list[Path] = []
    for system in SYSTEMS:
        result.extend((directory / f"test_{system}.csv", directory / f"test_{system}_metrics.json"))
    return result


def _normalise_relative_path(value: str) -> Path:
    return Path(str(value).replace("\\", os.sep).replace("/", os.sep))


def verify_validation_selection(root: Path | None = None) -> dict[str, Any]:
    root = root or repo_root()
    path = root / "outputs" / "normalization" / "selection" / "normalization_selection_manifest.json"
    require_files([path])
    manifest = load_json(path)
    expected = {
        "selection_population": "validation_only",
        "test_results_consulted": False,
        "validation_records": EXPECTED_VALIDATION_RECORDS,
        "selected_system": "selective_byt5",
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise RuntimeError(f"Frozen validation selection mismatch: {key}={manifest.get(key)!r}, expected {value!r}")
    artifacts = manifest.get("artifacts") or {}
    failures: list[str] = []
    checked = 0
    for system in SYSTEMS:
        item = artifacts.get(system) or {}
        for path_key, hash_key in (("prediction_path", "prediction_sha256"), ("metrics_path", "metrics_sha256")):
            relative = str(item.get(path_key) or "")
            expected_hash = str(item.get(hash_key) or "").lower()
            target = root / _normalise_relative_path(relative)
            checked += 1
            if not relative or not expected_hash or not target.is_file() or sha256(target).lower() != expected_hash:
                failures.append(f"{system}:{path_key}")
    if failures:
        raise RuntimeError("Frozen validation artifacts changed or are missing: " + ", ".join(failures))
    return {
        "manifest": str(path),
        "manifest_sha256": sha256(path),
        "artifacts_checked": checked,
        "selection_population": manifest["selection_population"],
        "validation_records": manifest["validation_records"],
        "selected_system": manifest["selected_system"],
        "test_results_consulted_at_selection": manifest["test_results_consulted"],
    }


def expected_test_ids(root: Path | None = None) -> set[str]:
    root = root or repo_root()
    split_csv, split_manifest = split_paths(root)
    require_files([split_csv, split_manifest])
    manifest = load_json(split_manifest)
    if manifest.get("records") != 5124 or (manifest.get("split_counts") or {}).get("test") != EXPECTED_TEST_RECORDS:
        raise RuntimeError("Normalization split manifest does not identify the frozen 5,124-record / 741-test split.")
    result: set[str] = set()
    with split_csv.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"example_id", "split"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise RuntimeError(f"Frozen split is missing columns: {sorted(missing)}")
        for row in reader:
            if str(row.get("split") or "").strip() == "test":
                ident = str(row.get("example_id") or "").strip()
                if not ident:
                    raise RuntimeError("Frozen test split contains an empty example_id.")
                if ident in result:
                    raise RuntimeError(f"Frozen test split contains duplicate example_id: {ident}")
                result.add(ident)
    if len(result) != EXPECTED_TEST_RECORDS:
        raise RuntimeError(f"Expected {EXPECTED_TEST_RECORDS} normalization test IDs; found {len(result)}.")
    return result


def verify_prediction_csv(path: Path, system: str, expected_ids: set[str]) -> dict[str, Any]:
    required = {
        "example_id", "split", "system", "raw_text", "reference_text",
        "candidate_text", "prediction_text", "protected_tokens_preserved",
    }
    observed: set[str] = set()
    row_count = 0
    protected_failures = 0
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise RuntimeError(f"{path} is missing columns: {sorted(missing)}")
        for row in reader:
            row_count += 1
            ident = str(row.get("example_id") or "").strip()
            if ident in observed:
                raise RuntimeError(f"Duplicate example_id {ident!r} in {path}")
            observed.add(ident)
            if row.get("split") != "test" or row.get("system") != system:
                raise RuntimeError(f"Wrong split/system at row {row_count + 1} in {path}")
            protected = str(row.get("protected_tokens_preserved") or "").strip().lower()
            if protected not in {"true", "1", "yes"}:
                protected_failures += 1
    if row_count != EXPECTED_TEST_RECORDS or observed != expected_ids:
        missing = sorted(expected_ids - observed)[:5]
        unexpected = sorted(observed - expected_ids)[:5]
        raise RuntimeError(
            f"TEST population mismatch for {system}: rows={row_count}, missing={missing}, unexpected={unexpected}"
        )
    if system == "selective_byt5" and protected_failures:
        raise RuntimeError(f"Selective ByT5 has {protected_failures} protected-token failures on TEST.")
    return {
        "path": str(path),
        "sha256": sha256(path),
        "records": row_count,
        "protected_token_failures": protected_failures,
    }


def verify_test_outputs(root: Path | None = None) -> dict[str, Any]:
    root = root or repo_root()
    ids = expected_test_ids(root)
    directory = prediction_dir(root)
    systems: dict[str, Any] = {}
    for system in SYSTEMS:
        csv_path = directory / f"test_{system}.csv"
        metrics_path = directory / f"test_{system}_metrics.json"
        require_files([csv_path, metrics_path])
        csv_report = verify_prediction_csv(csv_path, system, ids)
        metrics = load_json(metrics_path)
        if metrics.get("split") != "test" or metrics.get("system") != system:
            raise RuntimeError(f"Metrics identity mismatch: {metrics_path}")
        if int(metrics.get("records", -1)) != EXPECTED_TEST_RECORDS:
            raise RuntimeError(f"Metrics population mismatch: {metrics_path}")
        if not isinstance(metrics.get("metrics"), dict) or not isinstance(metrics.get("bootstrap_95_ci"), dict):
            raise RuntimeError(f"Metrics or bootstrap interval missing: {metrics_path}")
        systems[system] = {
            "prediction": csv_report,
            "metrics_path": str(metrics_path),
            "metrics_sha256": sha256(metrics_path),
            "metrics": metrics["metrics"],
            "bootstrap_95_ci": metrics["bootstrap_95_ci"],
        }
    return {"records": len(ids), "systems": systems}


def write_checksum_manifest(directory: Path) -> Path:
    rows = []
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            rows.append(f"{sha256(path)}  {path.relative_to(directory).as_posix()}")
    target = directory / "SHA256SUMS.txt"
    atomic_text(target, "\n".join(rows) + "\n", encoding="ascii")
    return target


def verify_checksum_manifest(directory: Path) -> dict[str, Any]:
    sums = directory / "SHA256SUMS.txt"
    require_files([sums])
    failures: list[str] = []
    checked = 0
    for line in sums.read_text(encoding="ascii").splitlines():
        if not line.strip():
            continue
        try:
            expected, relative = line.split("  ", 1)
        except ValueError as exc:
            raise RuntimeError(f"Malformed checksum line: {line!r}") from exc
        target = directory / Path(relative)
        checked += 1
        if not target.is_file() or sha256(target).lower() != expected.lower():
            failures.append(relative)
    if failures:
        raise RuntimeError("Checksum verification failed: " + ", ".join(failures[:10]))
    return {"files_checked": checked, "sha256sums_sha256": sha256(sums)}
