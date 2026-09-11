"""Validate and freeze the already-selected normalization intrinsic TEST.

This script never predicts, trains, or tunes.  It only verifies completed
741-record TEST outputs and creates an immutable evidence package.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VERSION = "phase2_normalization_intrinsic_test_v1"
EXPECTED_RECORDS = 741
SYSTEMS = (
    "raw",
    "most_frequent_replacement",
    "rules",
    "byt5",
    "selective_byt5",
    "rules_then_byt5",
)
CORE_SYSTEMS = {"raw", "rules", "byt5", "selective_byt5"}
METRICS = (
    "wer",
    "cer",
    "exact_match",
    "error_reduction_rate",
    "change_precision",
    "change_recall",
    "change_f1",
    "protected_token_accuracy",
)


class MissingEvidence(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def source_key(path: Path, repo: Path) -> str:
    try:
        return str(path.relative_to(repo)).replace("\\", "/")
    except ValueError:
        return f"external/{path.name}"


def git_commit(repo: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--verify", "HEAD"], cwd=repo, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def verify_sha_manifest(directory: Path) -> None:
    manifest = directory / "SHA256SUMS.txt"
    if not manifest.is_file():
        raise RuntimeError(f"Missing checksum manifest: {manifest}")
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split("  ", 1)
        target = directory / Path(relative)
        if not target.is_file() or sha256(target) != expected:
            raise RuntimeError(f"Frozen checksum mismatch: {target}")


def expected_test_ids(split_path: Path) -> set[str]:
    with split_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"example_id", "split"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise RuntimeError(f"Frozen split is missing columns: {sorted(missing)}")
        ids = {str(row["example_id"]) for row in reader if str(row["split"]).lower() == "test"}
    if len(ids) != EXPECTED_RECORDS:
        raise RuntimeError(f"Expected {EXPECTED_RECORDS} TEST IDs, found {len(ids)} in {split_path}")
    return ids


def prediction_ids(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"example_id", "raw_text", "prediction_text", "reference_text"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise RuntimeError(f"Prediction file {path} is missing columns: {sorted(missing)}")
        rows = list(reader)
    ids = [str(row["example_id"]) for row in rows]
    if len(rows) != EXPECTED_RECORDS or len(set(ids)) != EXPECTED_RECORDS:
        raise RuntimeError(f"Prediction population is not {EXPECTED_RECORDS} unique rows: {path}")
    return set(ids)


def validate(repo: Path) -> dict[str, Any]:
    selection_path = repo / "outputs/normalization/selection/normalization_selection_manifest.json"
    split_manifest_path = repo / "data/splits/normalization_cluster_safe_v1.manifest.json"
    if not selection_path.is_file() or not split_manifest_path.is_file():
        raise RuntimeError("Frozen selection or split manifest is missing.")

    selection = read_json(selection_path)
    if selection.get("selected_system") != "selective_byt5":
        raise RuntimeError("The frozen validation selection is not selective_byt5.")
    if selection.get("selection_population") != "validation_only":
        raise RuntimeError("Selection was not made on validation_only.")
    if selection.get("test_results_consulted") is not False:
        raise RuntimeError("Selection manifest does not prove that TEST was unconsulted.")
    if int(selection.get("validation_records", -1)) != 926:
        raise RuntimeError("Frozen validation population is not 926 records.")
    artifacts = selection.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(SYSTEMS):
        raise RuntimeError("Frozen selection manifest does not contain all six validation artifacts.")
    for system in SYSTEMS:
        item = artifacts[system]
        for path_key, hash_key in (
            ("prediction_path", "prediction_sha256"),
            ("metrics_path", "metrics_sha256"),
        ):
            source = repo / Path(str(item[path_key]).replace("\\", "/"))
            if not source.is_file() or sha256(source) != str(item[hash_key]):
                raise RuntimeError(f"Frozen validation artifact mismatch for {system}: {source}")

    split_manifest = read_json(split_manifest_path)
    if int(split_manifest.get("split_counts", {}).get("test", -1)) != EXPECTED_RECORDS:
        raise RuntimeError("Split manifest does not specify the 741-record TEST.")
    split_path = repo / Path(str(split_manifest["output_path"]).replace("\\", "/"))
    if not split_path.is_file():
        raise RuntimeError(f"Frozen split CSV is missing: {split_path}")
    test_ids = expected_test_ids(split_path)

    prediction_dir = repo / "outputs/normalization/predictions/byt5_gold_v1"
    missing_files: list[Path] = []
    systems: dict[str, Any] = {}
    for system in SYSTEMS:
        prediction_path = prediction_dir / f"test_{system}.csv"
        metrics_path = prediction_dir / f"test_{system}_metrics.json"
        system_missing = False
        for path in (prediction_path, metrics_path):
            if not path.is_file():
                missing_files.append(path)
                system_missing = True
        if system_missing:
            continue
        observed = prediction_ids(prediction_path)
        if observed != test_ids:
            raise RuntimeError(f"TEST ID mismatch for {system}.")
        payload = read_json(metrics_path)
        if payload.get("split") != "test" or payload.get("system") != system:
            raise RuntimeError(f"Metric identity mismatch for {system}: {metrics_path}")
        if int(payload.get("records", -1)) != EXPECTED_RECORDS:
            raise RuntimeError(f"Metric population mismatch for {system}: {metrics_path}")
        scores = payload.get("metrics", {})
        intervals = payload.get("bootstrap_95_ci", {})
        absent_metrics = [name for name in METRICS if name not in scores]
        if absent_metrics:
            raise RuntimeError(f"Missing metrics for {system}: {absent_metrics}")
        systems[system] = {
            "prediction_path": prediction_path,
            "metrics_path": metrics_path,
            "payload": payload,
            "metrics": scores,
            "bootstrap_95_ci": intervals,
        }

    if missing_files:
        details = "\n".join(f"  - {path.relative_to(repo)}" for path in missing_files)
        raise MissingEvidence("Missing normalization TEST evidence:\n" + details)
    return {
        "selection_path": selection_path,
        "split_manifest_path": split_manifest_path,
        "split_path": split_path,
        "systems": systems,
    }


def metric_text(value: Any) -> str:
    return "" if value is None else f"{float(value):.6f}"


def freeze(repo: Path, evidence: dict[str, Any]) -> Path:
    target = repo / "outputs/frozen" / VERSION
    if target.exists():
        verify_sha_manifest(target)
        manifest = read_json(target / "FREEZE_MANIFEST.json")
        if manifest.get("status") != "complete" or manifest.get("version") != VERSION:
            raise RuntimeError(f"Existing freeze is not a complete {VERSION}: {target}")
        print(f"NORMALIZATION_TEST_FREEZE_ALREADY_COMPLETE -> {target}")
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=VERSION + ".", dir=target.parent))
    try:
        copied = staging / "evidence"
        copied.mkdir()
        shutil.copy2(evidence["selection_path"], copied / evidence["selection_path"].name)
        shutil.copy2(evidence["split_manifest_path"], copied / evidence["split_manifest_path"].name)
        shutil.copy2(evidence["split_path"], copied / evidence["split_path"].name)

        rows: list[dict[str, Any]] = []
        for system in SYSTEMS:
            item = evidence["systems"][system]
            shutil.copy2(item["prediction_path"], copied / item["prediction_path"].name)
            shutil.copy2(item["metrics_path"], copied / item["metrics_path"].name)
            row: dict[str, Any] = {
                "system": system,
                "role": "core_thesis_comparison" if system in CORE_SYSTEMS else "additional_comparator",
                "records": EXPECTED_RECORDS,
            }
            for name in METRICS:
                row[name] = item["metrics"][name]
                interval = item["bootstrap_95_ci"].get(name)
                row[f"{name}_ci_low"] = interval[0] if interval else ""
                row[f"{name}_ci_high"] = interval[1] if interval else ""
            rows.append(row)

        fieldnames = list(rows[0])
        with (staging / "normalization_test_results.csv").open("w", encoding="utf-8", newline="") as sink:
            writer = csv.DictWriter(sink, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        table_lines = [
            "# Normalization intrinsic TEST results",
            "",
            "Population: 741 records from the frozen cluster-safe TEST split. Selection was performed on the 926-record validation split before TEST access.",
            "",
            "| System | Role | WER | CER | Exact match | Change F1 | Protected-token accuracy |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
        for row in rows:
            table_lines.append(
                "| {system} | {role} | {wer} | {cer} | {exact} | {change} | {protected} |".format(
                    system=row["system"],
                    role=row["role"],
                    wer=metric_text(row["wer"]),
                    cer=metric_text(row["cer"]),
                    exact=metric_text(row["exact_match"]),
                    change=metric_text(row["change_f1"]),
                    protected=metric_text(row["protected_token_accuracy"]),
                )
            )
        table_lines += [
            "",
            "The primary frozen system remains `selective_byt5`. These metrics measure text agreement with the annotated reference; they do not by themselves establish downstream maintenance correctness.",
            "",
        ]
        (staging / "NORMALIZATION_TEST_RESULTS.md").write_text("\n".join(table_lines), encoding="utf-8")

        source_files = [
            evidence["selection_path"], evidence["split_manifest_path"], evidence["split_path"],
            Path(__file__).resolve(),
            *[evidence["systems"][s]["prediction_path"] for s in SYSTEMS],
            *[evidence["systems"][s]["metrics_path"] for s in SYSTEMS],
        ]
        manifest = {
            "version": VERSION,
            "status": "complete",
            "created_utc": utc_now(),
            "repository_commit": git_commit(repo),
            "experiment": "intrinsic normalization final test",
            "selection_population": "validation_only",
            "validation_records": 926,
            "test_records": EXPECTED_RECORDS,
            "selected_system": "selective_byt5",
            "systems": list(SYSTEMS),
            "training_performed": False,
            "retuning_performed": False,
            "source_sha256": {
                source_key(path, repo): sha256(path) for path in source_files
            },
        }
        write_json(staging / "FREEZE_MANIFEST.json", manifest)

        files = sorted(path for path in staging.rglob("*") if path.is_file())
        sums = "\n".join(
            f"{sha256(path)}  {path.relative_to(staging).as_posix()}" for path in files
        ) + "\n"
        (staging / "SHA256SUMS.txt").write_text(sums, encoding="utf-8")
        os.replace(staging, target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    verify_sha_manifest(target)
    print(f"NORMALIZATION_TEST_FREEZE_COMPLETE -> {target}")
    return target


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    mode = result.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--freeze", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    repo = args.repo_root.resolve()
    try:
        evidence = validate(repo)
        print("NORMALIZATION_TEST_EVIDENCE_VALID records=741 systems=6")
        if args.freeze:
            freeze(repo, evidence)
        return 0
    except MissingEvidence as exc:
        print(str(exc), file=sys.stderr)
        return 10
    except Exception as exc:
        print(f"NORMALIZATION_TEST_INVALID: {exc}", file=sys.stderr)
        return 11


if __name__ == "__main__":
    raise SystemExit(main())
