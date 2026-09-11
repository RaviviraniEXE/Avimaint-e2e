"""Verify both Phase 2 freezes and create the completion manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VERSION = "phase2_evidence_completion_v1"
NORMALIZATION = "phase2_normalization_intrinsic_test_v1"
ROBUSTNESS = "phase2_selective_robustness_v1"


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


def verify(directory: Path, expected_version: str) -> dict[str, Any]:
    sums = directory / "SHA256SUMS.txt"
    manifest_path = directory / "FREEZE_MANIFEST.json"
    if not sums.is_file() or not manifest_path.is_file():
        raise RuntimeError(f"Incomplete freeze: {directory}")
    for line in sums.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split("  ", 1)
        target = directory / Path(relative)
        if not target.is_file() or sha256(target) != expected:
            raise RuntimeError(f"Checksum mismatch: {target}")
    manifest = read_json(manifest_path)
    if manifest.get("version") != expected_version or manifest.get("status") != "complete":
        raise RuntimeError(f"Wrong or incomplete freeze manifest: {manifest_path}")
    if manifest.get("training_performed") is not False or manifest.get("retuning_performed") is not False:
        raise RuntimeError(f"Phase 2 freeze violates the no-training/no-retuning policy: {manifest_path}")
    return manifest


def finalize(repo: Path) -> Path:
    frozen = repo / "outputs/frozen"
    normalization_dir = frozen / NORMALIZATION
    robustness_dir = frozen / ROBUSTNESS
    normalization_manifest = verify(normalization_dir, NORMALIZATION)
    robustness_manifest = verify(robustness_dir, ROBUSTNESS)
    target = frozen / VERSION

    identities = {
        "normalization_freeze_manifest_sha256": sha256(normalization_dir / "FREEZE_MANIFEST.json"),
        "normalization_sha256s_sha256": sha256(normalization_dir / "SHA256SUMS.txt"),
        "robustness_freeze_manifest_sha256": sha256(robustness_dir / "FREEZE_MANIFEST.json"),
        "robustness_sha256s_sha256": sha256(robustness_dir / "SHA256SUMS.txt"),
    }
    if target.exists():
        existing = verify(target, VERSION)
        if existing.get("component_identity") != identities:
            raise RuntimeError("Existing Phase 2 completion manifest refers to different component freezes.")
        print(f"PHASE2_ALREADY_COMPLETE -> {target}")
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=VERSION + ".", dir=target.parent))
    try:
        manifest = {
            "version": VERSION,
            "status": "complete",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "scope": [
                "741-record intrinsic normalization TEST",
                "final Selective retrieval robustness under a fixed supplementary protocol",
            ],
            "normalization": {
                "selected_system": normalization_manifest["selected_system"],
                "test_records": normalization_manifest["test_records"],
                "systems": normalization_manifest["systems"],
                "selection_population": normalization_manifest["selection_population"],
            },
            "robustness": {
                "classification": robustness_manifest["classification"],
                "representation": robustness_manifest["representation"],
                "evaluable_queries": robustness_manifest["evaluable_queries"],
                "selected_configuration": robustness_manifest["selected_configuration"],
                "clean_parity_with_frozen_rq4": robustness_manifest["clean_parity_with_frozen_rq4"],
            },
            "training_performed": False,
            "retuning_performed": False,
            "component_identity": identities,
            "thesis_claim_boundary": (
                "Normalization TEST is the held-out intrinsic evaluation selected on validation only. "
                "Selective robustness is a supplementary post-hoc locked-protocol analysis and must not "
                "be described as a newly preregistered confirmatory RQ4 experiment."
            ),
        }
        write_json(staging / "PHASE2_COMPLETION_MANIFEST.json", manifest)
        write_json(staging / "FREEZE_MANIFEST.json", manifest)
        report = """# Phase 2 completion report

Phase 2 closes the two evidence gaps identified during the repository audit.

## 1. Intrinsic normalization final test

- Frozen cluster-safe TEST population: **741 records**.
- Frozen selection population: **926 validation records only**.
- Primary system: **Selective ByT5**.
- Comparators: Raw, most-frequent replacement, rules, ByT5, and rules-then-ByT5.
- Outputs include per-system predictions, WER, CER, exact match, error-reduction rate, change precision/recall/F1, protected-token accuracy, and bootstrap confidence intervals.

Use `../phase2_normalization_intrinsic_test_v1/NORMALIZATION_TEST_RESULTS.md` for the thesis-ready results table.

## 2. Final Selective robustness

- Representation: **Selective ByT5**.
- Retrieval configuration: **Selective canonical BM25, tau 0.15, cluster-expanded aggregation**.
- Population: **925 frozen TEST records; 828 evaluable action-family queries**.
- Stressors: truncation at 10/20/30%, spelling noise at 5/10%, and missing structured evidence.
- Clean parity with the frozen RQ4 result is mandatory.
- No training, parameter selection, or retuning is performed.

Use `../phase2_selective_robustness_v1/SELECTIVE_ROBUSTNESS_RESULTS.md` for the thesis-ready results table.

## Reporting boundary

The normalization result is the held-out intrinsic test selected from validation only. The Selective robustness study is a **supplementary post-hoc analysis executed under a fixed protocol** because the main RQ4 TEST had already been opened and frozen. It must not be called newly preregistered or used to retune the system.
"""
        (staging / "PHASE2_COMPLETION_REPORT.md").write_text(report, encoding="utf-8")
        files = sorted(path for path in staging.rglob("*") if path.is_file())
        (staging / "SHA256SUMS.txt").write_text(
            "\n".join(f"{sha256(path)}  {path.relative_to(staging).as_posix()}" for path in files) + "\n",
            encoding="utf-8",
        )
        os.replace(staging, target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    verify(target, VERSION)
    print(f"PHASE2_COMPLETE -> {target}")
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    finalize(args.repo_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
