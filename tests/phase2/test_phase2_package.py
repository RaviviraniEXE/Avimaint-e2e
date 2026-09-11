from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[2]


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, PACKAGE / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


normalization = load("phase2_normalization", "scripts/phase2/freeze_normalization_test.py")
robustness = load("phase2_robustness", "scripts/phase2/run_selective_robustness.py")
finalization = load("phase2_finalization", "scripts/phase2/finalize_phase2.py")


class RobustnessHelperTests(unittest.TestCase):
    def test_truncation_and_noise_are_deterministic(self):
        self.assertEqual(robustness.truncate("one two three four", 0.25), "one two three")
        seed = robustness.stable_seed("A-1", "spelling_noise", 0.10)
        first = robustness.spelling_noise("HYDRAULIC pressure low", 0.10, seed)
        second = robustness.spelling_noise("HYDRAULIC pressure low", 0.10, seed)
        self.assertEqual(first, second)
        self.assertNotEqual(first, "HYDRAULIC pressure low")

    def test_clean_parity_guard(self):
        metrics = {name: 0.5 for name in robustness.HEADLINE}
        robustness.validate_clean_parity(metrics, {"selected_configuration_metrics": metrics})
        altered = dict(metrics)
        altered["hit_at_1"] = 0.4
        with self.assertRaises(RuntimeError):
            robustness.validate_clean_parity(altered, {"selected_configuration_metrics": metrics})


class NormalizationFreezeTests(unittest.TestCase):
    def build_fixture(self, root: Path) -> None:
        selection = root / "outputs/normalization/selection"
        predictions = root / "outputs/normalization/predictions/byt5_gold_v1"
        splits = root / "data/splits"
        selection.mkdir(parents=True)
        predictions.mkdir(parents=True)
        splits.mkdir(parents=True)
        validation_artifacts = {}
        for system in normalization.SYSTEMS:
            validation_prediction = predictions / f"validation_{system}.csv"
            validation_metrics = predictions / f"validation_{system}_metrics.json"
            validation_prediction.write_text(f"validation prediction {system}\n", encoding="utf-8")
            validation_metrics.write_text(json.dumps({"system": system}), encoding="utf-8")
            validation_artifacts[system] = {
                "prediction_path": str(validation_prediction.relative_to(root)),
                "prediction_sha256": hashlib.sha256(validation_prediction.read_bytes()).hexdigest(),
                "metrics_path": str(validation_metrics.relative_to(root)),
                "metrics_sha256": hashlib.sha256(validation_metrics.read_bytes()).hexdigest(),
            }
        (selection / "normalization_selection_manifest.json").write_text(
            json.dumps({
                "selected_system": "selective_byt5",
                "selection_population": "validation_only",
                "test_results_consulted": False,
                "validation_records": 926,
                "artifacts": validation_artifacts,
            }),
            encoding="utf-8",
        )
        (splits / "normalization_cluster_safe_v1.manifest.json").write_text(
            json.dumps({
                "output_path": "data\\splits\\normalization_cluster_safe_v1.csv",
                "split_counts": {"train": 3457, "validation": 926, "test": 741},
            }),
            encoding="utf-8",
        )
        with (splits / "normalization_cluster_safe_v1.csv").open("w", newline="", encoding="utf-8") as sink:
            writer = csv.DictWriter(sink, fieldnames=["example_id", "split"])
            writer.writeheader()
            writer.writerows({"example_id": f"T-{index:04d}", "split": "test"} for index in range(741))

        metric_values = {name: 0.5 for name in normalization.METRICS}
        intervals = {name: [0.4, 0.6] for name in normalization.METRICS}
        for system in normalization.SYSTEMS:
            with (predictions / f"test_{system}.csv").open("w", newline="", encoding="utf-8") as sink:
                writer = csv.DictWriter(
                    sink,
                    fieldnames=["example_id", "raw_text", "prediction_text", "reference_text"],
                )
                writer.writeheader()
                writer.writerows({
                    "example_id": f"T-{index:04d}",
                    "raw_text": "raw",
                    "prediction_text": "normalized",
                    "reference_text": "normalized",
                } for index in range(741))
            (predictions / f"test_{system}_metrics.json").write_text(
                json.dumps({
                    "split": "test",
                    "system": system,
                    "records": 741,
                    "metrics": metric_values,
                    "bootstrap_95_ci": intervals,
                }),
                encoding="utf-8",
            )

    def test_validate_freeze_and_verify(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.build_fixture(root)
            evidence = normalization.validate(root)
            target = normalization.freeze(root, evidence)
            normalization.verify_sha_manifest(target)
            manifest = json.loads((target / "FREEZE_MANIFEST.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["test_records"], 741)
            self.assertFalse(manifest["training_performed"])

    def test_missing_output_is_detected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.build_fixture(root)
            (root / "outputs/normalization/predictions/byt5_gold_v1/test_byt5_metrics.json").unlink()
            with self.assertRaises(normalization.MissingEvidence):
                normalization.validate(root)


class FinalizationTests(unittest.TestCase):
    @staticmethod
    def component(root: Path, version: str, payload: dict) -> None:
        directory = root / "outputs/frozen" / version
        directory.mkdir(parents=True)
        manifest = {
            "version": version,
            "status": "complete",
            "training_performed": False,
            "retuning_performed": False,
            **payload,
        }
        manifest_path = directory / "FREEZE_MANIFEST.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        checksum = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        (directory / "SHA256SUMS.txt").write_text(
            f"{checksum}  FREEZE_MANIFEST.json\n", encoding="utf-8"
        )

    def test_completion_manifest_binds_both_freezes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.component(root, finalization.NORMALIZATION, {
                "selected_system": "selective_byt5",
                "test_records": 741,
                "systems": list(normalization.SYSTEMS),
                "selection_population": "validation_only",
            })
            self.component(root, finalization.ROBUSTNESS, {
                "classification": "supplementary_posthoc_locked_protocol",
                "representation": "selective_byt5",
                "evaluable_queries": 828,
                "selected_configuration": {
                    "retrieval_mode": "selective_canonical_bm25",
                    "tau": 0.15,
                    "aggregation": "cluster_expanded",
                },
                "clean_parity_with_frozen_rq4": True,
            })
            target = finalization.finalize(root)
            finalization.verify(target, finalization.VERSION)
            completion = json.loads((target / "PHASE2_COMPLETION_MANIFEST.json").read_text())
            self.assertEqual(completion["normalization"]["test_records"], 741)
            self.assertEqual(completion["robustness"]["evaluable_queries"], 828)


if __name__ == "__main__":
    unittest.main()
