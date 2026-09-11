from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

try:
    from .common import (
        SYSTEMS,
        prediction_dir,
        repo_root,
        test_artifacts,
        verify_prediction_csv,
        verify_test_outputs,
        verify_validation_selection,
        expected_test_ids,
    )
except ImportError:
    from common import (
        SYSTEMS,
        prediction_dir,
        repo_root,
        test_artifacts,
        verify_prediction_csv,
        verify_test_outputs,
        verify_validation_selection,
        expected_test_ids,
    )


def run_command(arguments: list[str], root: Path) -> None:
    print("RUN:", " ".join(arguments), flush=True)
    completed = subprocess.run(arguments, cwd=root, check=False)
    if completed.returncode:
        raise RuntimeError(f"Command failed with exit code {completed.returncode}: {' '.join(arguments)}")


def missing_test_outputs(root: Path) -> list[Path]:
    return [path for path in test_artifacts(root) if not path.is_file()]


def run_missing_test_outputs(root: Path) -> None:
    directory = prediction_dir(root)
    expected_ids = expected_test_ids(root)
    config = "configs/normalization/byt5_gold.yaml"
    for system in SYSTEMS:
        prediction = directory / f"test_{system}.csv"
        metrics = directory / f"test_{system}_metrics.json"
        if metrics.is_file() and not prediction.is_file():
            raise RuntimeError(
                f"Metrics exist without their prediction file for {system}: {metrics}. "
                "Move the partial TEST artifacts aside for audit before resuming."
            )
        if prediction.is_file():
            verify_prediction_csv(prediction, system, expected_ids)
            print(f"REUSE valid TEST prediction: {prediction}")
        else:
            run_command(
                [sys.executable, "-u", "-m", "avimaint.normalization", "predict", "--config", config, "--split", "test", "--system", system],
                root,
            )
            verify_prediction_csv(prediction, system, expected_ids)
        if metrics.is_file():
            print(f"REUSE existing TEST metrics: {metrics}")
        else:
            run_command(
                [sys.executable, "-u", "-m", "avimaint.normalization", "evaluate", "--config", config, "--split", "test", "--system", system],
                root,
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Guarded completion of the locked normalization TEST evidence")
    parser.add_argument("--mode", choices=["SAFE", "CONFIRM_TEST", "VERIFY_ONLY"], default="SAFE")
    args = parser.parse_args()
    root = repo_root()
    try:
        selection = verify_validation_selection(root)
        print(json.dumps({"validation_selection": selection}, indent=2))
        missing = missing_test_outputs(root)
        if missing and args.mode != "CONFIRM_TEST":
            print("\nMissing normalization TEST evidence:")
            for path in missing:
                print(f"  - {path.relative_to(root)}")
            print("\nThe TEST has not been opened by this hotfix. Run with CONFIRM_TEST after reviewing this list.")
            return 20
        if args.mode == "CONFIRM_TEST" and missing:
            print("\nCONFIRM_TEST accepted. This performs inference/evaluation only; it does not train or select a model.")
            run_missing_test_outputs(root)
        result = verify_test_outputs(root)
        print(json.dumps({
            "status": "verified",
            "population": "locked normalization test",
            "records": result["records"],
            "systems": list(result["systems"]),
            "training_performed": False,
            "retuning_performed": False,
        }, indent=2))
        print("PHASE2_NORMALIZATION_TEST_VERIFIED")
        return 0
    except (RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
