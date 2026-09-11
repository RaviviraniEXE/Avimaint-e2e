from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

try:
    from .common import (
        PHASE2_VERSION,
        SYSTEMS,
        atomic_json,
        atomic_text,
        load_json,
        prediction_dir,
        repo_root,
        sha256,
        split_paths,
        verify_checksum_manifest,
        verify_test_outputs,
        verify_validation_selection,
        write_checksum_manifest,
    )
except ImportError:
    from common import (
        PHASE2_VERSION,
        SYSTEMS,
        atomic_json,
        atomic_text,
        load_json,
        prediction_dir,
        repo_root,
        sha256,
        split_paths,
        verify_checksum_manifest,
        verify_test_outputs,
        verify_validation_selection,
        write_checksum_manifest,
    )


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def frozen_rq4_paths(root: Path) -> tuple[Path, Path, Path]:
    directory = root / "outputs" / "frozen" / "final_rq4_rq5_selective_final"
    return directory, directory / "FREEZE_MANIFEST.json", directory / "SHA256SUMS.txt"


def verify_rq4_freeze(root: Path) -> dict[str, Any]:
    directory, manifest_path, sums = frozen_rq4_paths(root)
    report = verify_checksum_manifest(directory)
    manifest = load_json(manifest_path)
    selected = manifest.get("selected_configuration") or {}
    expected = {
        "retrieval_mode": "selective_canonical_bm25",
        "tau": 0.15,
        "aggregation": "cluster_expanded",
    }
    if selected != expected or manifest.get("status") != "complete" or manifest.get("no_post_test_tuning") is not True:
        raise RuntimeError("Final RQ4/RQ5 freeze identity or selected configuration is incorrect.")
    return {
        "directory": str(directory),
        "manifest_sha256": sha256(manifest_path),
        "sha256sums_sha256": sha256(sums),
        "files_checked": report["files_checked"],
        "selected_configuration": selected,
    }


def verify_robustness(root: Path) -> dict[str, Any]:
    directory = root / "outputs" / "runs" / "phase2_final_protocol_robustness"
    report = verify_checksum_manifest(directory)
    manifest = load_json(directory / "RUN_MANIFEST.json")
    if manifest.get("status") != "complete" or not (manifest.get("clean_parity") or {}).get("passed"):
        raise RuntimeError("Final-protocol robustness result is incomplete or failed clean parity.")
    if (manifest.get("population") or {}).get("evaluable_queries") != 828:
        raise RuntimeError("Robustness population is not the 828-query locked test.")
    return {
        "directory": str(directory),
        "manifest_sha256": sha256(directory / "RUN_MANIFEST.json"),
        "sha256sums_sha256": sha256(directory / "SHA256SUMS.txt"),
        "files_checked": report["files_checked"],
        "configuration": manifest["configuration"],
        "clean_parity": manifest["clean_parity"],
    }


def current_source_identity(root: Path) -> dict[str, Any]:
    robustness_manifest = root / "outputs" / "runs" / "phase2_final_protocol_robustness" / "RUN_MANIFEST.json"
    identity: dict[str, Any] = {
        "validation_selection_manifest_sha256": sha256(root / "outputs" / "normalization" / "selection" / "normalization_selection_manifest.json"),
        "normalization_split_manifest_sha256": sha256(split_paths(root)[1]),
        "rq4_rq5_freeze_manifest_sha256": sha256(frozen_rq4_paths(root)[1]),
        "rq4_rq5_sha256sums_sha256": sha256(frozen_rq4_paths(root)[2]),
        "robustness_manifest_sha256": sha256(robustness_manifest),
        "normalization_test_artifacts": {},
    }
    directory = prediction_dir(root)
    for system in SYSTEMS:
        identity["normalization_test_artifacts"][system] = {
            "prediction_sha256": sha256(directory / f"test_{system}.csv"),
            "metrics_sha256": sha256(directory / f"test_{system}_metrics.json"),
        }
    return identity


def metric_value(system: dict[str, Any], name: str) -> float:
    return float((system.get("metrics") or {})[name])


def interval(system: dict[str, Any], name: str) -> str:
    values = (system.get("bootstrap_95_ci") or {}).get(name)
    if not isinstance(values, list) or len(values) != 2:
        return "not reported"
    return f"{float(values[0]):.4f} to {float(values[1]):.4f}"


def build_thesis_report(normalization: dict[str, Any], robustness_directory: Path) -> str:
    rows = [
        "# Phase 2 thesis results",
        "",
        "These results close the previously missing evidence. The normalization values below come from the locked 741-record test, after model selection on the separate 926-record validation population. No training or retuning was performed after opening the test.",
        "",
        "## Locked normalization test",
        "",
        "| System | WER | CER | Exact match | Change F1 | Protected-token accuracy | Exact-match 95% bootstrap CI |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    labels = {
        "raw": "Raw control",
        "most_frequent_replacement": "Most-frequent replacement",
        "rules": "Rules",
        "byt5": "ByT5",
        "selective_byt5": "Selective ByT5 (selected)",
        "rules_then_byt5": "Rules then ByT5",
    }
    for name in SYSTEMS:
        value = normalization["systems"][name]
        rows.append(
            f"| {labels[name]} | {metric_value(value, 'wer'):.6f} | {metric_value(value, 'cer'):.6f} | "
            f"{metric_value(value, 'exact_match'):.6f} | {metric_value(value, 'change_f1'):.6f} | "
            f"{metric_value(value, 'protected_token_accuracy'):.6f} | {interval(value, 'exact_match')} |"
        )
    rows.extend([
        "",
        "Interpret these figures as agreement with the expert normalization reference. They do not independently prove semantic correctness. The 926-record validation results may still be reported as model-selection evidence, but they must not be labelled as held-out test performance.",
        "",
        "## Supplementary robustness analysis",
        "",
        (robustness_directory / "ROBUSTNESS_THESIS_RESULTS.md").read_text(encoding="utf-8").strip(),
        "",
        "## Mandatory thesis edits",
        "",
        "1. Change the RQ1 evaluation population to the locked 741-record test and keep the 926 records labelled validation only.",
        "2. Replace the normalization result table and its confidence interval with the values above.",
        "3. Replace the Section 5.8 placeholder with the robustness table above and label it supplementary post-hoc fixed-protocol analysis.",
        "4. Do not alter or rerun the frozen RQ4/RQ5 results.",
        "",
    ])
    return "\n".join(rows)


def verify_phase2_freeze(directory: Path, root: Path) -> dict[str, Any]:
    report = verify_checksum_manifest(directory)
    manifest = load_json(directory / "FREEZE_MANIFEST.json")
    if manifest.get("version") != PHASE2_VERSION or manifest.get("status") != "complete":
        raise RuntimeError("Phase 2 freeze manifest identity mismatch.")
    if manifest.get("training_performed") is not False or manifest.get("retuning_performed") is not False:
        raise RuntimeError("Phase 2 freeze does not preserve the no-training/no-retuning policy.")
    current = current_source_identity(root)
    if manifest.get("source_identity") != current:
        raise RuntimeError("Phase 2 source identity changed after freezing.")
    return {"status": "verified", "files_checked": report["files_checked"], "directory": str(directory)}


def create_freeze(root: Path, destination: Path) -> None:
    validation = verify_validation_selection(root)
    normalization = verify_test_outputs(root)
    rq4 = verify_rq4_freeze(root)
    robustness = verify_robustness(root)
    if destination.exists():
        result = verify_phase2_freeze(destination, root)
        print(json.dumps(result, indent=2))
        print("PHASE2_FREEZE_ALREADY_COMPLETE")
        return

    stage = destination.with_name(destination.name + ".staging-" + dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
    if stage.exists():
        raise RuntimeError(f"Unexpected staging directory exists: {stage}")
    stage.mkdir(parents=True)
    try:
        normal_dir = stage / "normalization_test"
        normal_dir.mkdir()
        source_predictions = prediction_dir(root)
        for system in SYSTEMS:
            for suffix in (".csv", "_metrics.json"):
                source = source_predictions / f"test_{system}{suffix}"
                shutil.copy2(source, normal_dir / source.name)
        context = stage / "context"
        context.mkdir()
        shutil.copy2(root / "outputs" / "normalization" / "selection" / "normalization_selection_manifest.json", context)
        _split_csv, split_manifest = split_paths(root)
        shutil.copy2(split_manifest, context)
        shutil.copy2(frozen_rq4_paths(root)[1], context / "FINAL_RQ4_RQ5_FREEZE_MANIFEST.json")
        shutil.copy2(frozen_rq4_paths(root)[2], context / "FINAL_RQ4_RQ5_SHA256SUMS.txt")
        robustness_source = root / "outputs" / "runs" / "phase2_final_protocol_robustness"
        shutil.copytree(robustness_source, stage / "robustness")

        source_identity = current_source_identity(root)
        manifest = {
            "version": PHASE2_VERSION,
            "created_utc": utc_now(),
            "status": "complete",
            "purpose": "Complete the previously missing locked RQ1 normalization test and supplementary fixed-protocol robustness evidence.",
            "training_performed": False,
            "retuning_performed": False,
            "normalization": {
                "selection_population": "validation_only",
                "selection_records": 926,
                "locked_test_records": normalization["records"],
                "systems": list(normalization["systems"]),
                "test_opened_only_after_explicit_confirmation": True,
                "validation_verification": validation,
            },
            "robustness": robustness,
            "rq4_rq5": {
                "unchanged": True,
                "verification": rq4,
            },
            "source_identity": source_identity,
            "interpretation_boundaries": {
                "normalization": "agreement with expert reference; not independent semantic correctness",
                "retrieval": "agreement with recorded historical action family; not technical correctness or approval",
                "robustness": "supplementary post-hoc fixed-protocol analysis",
            },
        }
        atomic_json(stage / "FREEZE_MANIFEST.json", manifest)
        atomic_text(stage / "PHASE2_THESIS_RESULTS.md", build_thesis_report(normalization, robustness_source))
        write_checksum_manifest(stage)
        verify_checksum_manifest(stage)
        os.replace(stage, destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    result = verify_phase2_freeze(destination, root)
    print(json.dumps(result, indent=2))
    print("PHASE2_FREEZE_COMPLETE")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or verify the immutable thesis Phase 2 evidence freeze")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    root = repo_root()
    destination = root / "outputs" / "frozen" / "phase2_missing_evidence_final"
    try:
        if args.verify_only:
            print(json.dumps(verify_phase2_freeze(destination, root), indent=2))
            print("PHASE2_FREEZE_VERIFIED")
        else:
            create_freeze(root, destination)
        return 0
    except (RuntimeError, ValueError, KeyError, json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
