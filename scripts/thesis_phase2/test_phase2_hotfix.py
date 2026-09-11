from __future__ import annotations

import csv
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from . import common, phase2_freeze
from .final_protocol_robustness import (
    compare_clean_metrics,
    recover_verified_staging,
    spelling_noise,
    truncate,
)


class Phase2HotfixTests(unittest.TestCase):
    def test_truncation_is_deterministic(self) -> None:
        self.assertEqual(truncate("one two three four five", 0.40), "one two three")
        self.assertEqual(truncate("single", 0.90), "single")

    def test_spelling_noise_is_deterministic_and_preserves_digits(self) -> None:
        source = "num_4 intake ratio_20_80"
        first = spelling_noise(source, 0.10, "Q-1")
        second = spelling_noise(source, 0.10, "Q-1")
        self.assertEqual(first, second)
        self.assertEqual("".join(ch for ch in first if ch.isdigit()), "42080")

    def test_clean_metric_parity_accepts_exact_values(self) -> None:
        value = {name: 0.5 for name in (
            "hit_at_1", "hit_at_3", "hit_at_5", "mrr", "ndcg_at_5",
            "macro_action_family_recall", "answer_rate",
        )}
        value["queries"] = 828
        report = compare_clean_metrics(value, dict(value))
        self.assertTrue(report["passed"])

    def test_clean_metric_parity_fails_closed(self) -> None:
        value = {name: 0.5 for name in (
            "hit_at_1", "hit_at_3", "hit_at_5", "mrr", "ndcg_at_5",
            "macro_action_family_recall", "answer_rate",
        )}
        value["queries"] = 828
        changed = dict(value)
        changed["hit_at_1"] = 0.49
        with self.assertRaises(RuntimeError):
            compare_clean_metrics(changed, value)

    def test_checksum_manifest_detects_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "one.txt").write_text("frozen\n", encoding="utf-8")
            common.write_checksum_manifest(root)
            self.assertEqual(common.verify_checksum_manifest(root)["files_checked"], 1)
            (root / "one.txt").write_text("changed\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                common.verify_checksum_manifest(root)

    def test_verified_staging_is_atomically_recovered(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            stage = root / "result.staging"
            output = root / "result"
            identity = {"frozen_input": "sha256-example"}
            stage.mkdir()
            common.atomic_json(stage / "RUN_MANIFEST.json", {
                "input_identity": identity,
                "clean_parity": {"passed": True},
            })
            (stage / "result.txt").write_text("complete\n", encoding="utf-8")
            common.write_checksum_manifest(stage)
            self.assertTrue(recover_verified_staging(stage, output, identity))
            self.assertFalse(stage.exists())
            self.assertEqual((output / "result.txt").read_text(encoding="utf-8"), "complete\n")

    def test_prediction_population_and_identity(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "test_raw.csv"
            ids = {f"id-{index}" for index in range(common.EXPECTED_TEST_RECORDS)}
            fields = [
                "example_id", "split", "system", "raw_text", "reference_text",
                "candidate_text", "prediction_text", "protected_tokens_preserved",
            ]
            with path.open("w", encoding="utf-8", newline="") as target:
                writer = csv.DictWriter(target, fieldnames=fields)
                writer.writeheader()
                for ident in sorted(ids):
                    writer.writerow({
                        "example_id": ident, "split": "test", "system": "raw",
                        "raw_text": "raw", "reference_text": "reference",
                        "candidate_text": "raw", "prediction_text": "raw",
                        "protected_tokens_preserved": "True",
                    })
            report = common.verify_prediction_csv(path, "raw", ids)
            self.assertEqual(report["records"], common.EXPECTED_TEST_RECORDS)

    def test_phase2_freeze_is_atomically_promoted(self) -> None:
        """Exercise the final staging-to-freeze move that failed in v1.1."""
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            destination = root / "outputs" / "frozen" / "phase2_missing_evidence_final"

            predictions = root / "predictions"
            predictions.mkdir()
            for system in common.SYSTEMS:
                (predictions / f"test_{system}.csv").write_text("example_id\n", encoding="utf-8")
                (predictions / f"test_{system}_metrics.json").write_text("{}\n", encoding="utf-8")

            selection = root / "outputs" / "normalization" / "selection" / "normalization_selection_manifest.json"
            selection.parent.mkdir(parents=True)
            selection.write_text("{}\n", encoding="utf-8")

            split_manifest = root / "split_manifest.json"
            split_manifest.write_text("{}\n", encoding="utf-8")

            rq4_directory = root / "rq4"
            rq4_directory.mkdir()
            rq4_manifest = rq4_directory / "FREEZE_MANIFEST.json"
            rq4_sums = rq4_directory / "SHA256SUMS.txt"
            rq4_manifest.write_text("{}\n", encoding="utf-8")
            rq4_sums.write_text("example\n", encoding="utf-8")

            robustness = root / "outputs" / "runs" / "phase2_final_protocol_robustness"
            robustness.mkdir(parents=True)
            (robustness / "result.txt").write_text("verified\n", encoding="utf-8")

            with ExitStack() as stack:
                stack.enter_context(mock.patch.object(phase2_freeze, "prediction_dir", return_value=predictions))
                stack.enter_context(mock.patch.object(phase2_freeze, "split_paths", return_value=(root / "split.csv", split_manifest)))
                stack.enter_context(mock.patch.object(phase2_freeze, "frozen_rq4_paths", return_value=(rq4_directory, rq4_manifest, rq4_sums)))
                stack.enter_context(mock.patch.object(phase2_freeze, "verify_validation_selection", return_value={"status": "verified"}))
                stack.enter_context(mock.patch.object(phase2_freeze, "verify_test_outputs", return_value={"records": 741, "systems": {system: {} for system in common.SYSTEMS}}))
                stack.enter_context(mock.patch.object(phase2_freeze, "verify_rq4_freeze", return_value={"status": "verified"}))
                stack.enter_context(mock.patch.object(phase2_freeze, "verify_robustness", return_value={"status": "verified"}))
                stack.enter_context(mock.patch.object(phase2_freeze, "current_source_identity", return_value={"fixture": "identity"}))
                stack.enter_context(mock.patch.object(phase2_freeze, "build_thesis_report", return_value="# Phase 2 results\n"))
                stack.enter_context(mock.patch.object(phase2_freeze, "verify_phase2_freeze", return_value={"status": "verified"}))
                phase2_freeze.create_freeze(root, destination)

            self.assertTrue(destination.is_dir())
            self.assertTrue((destination / "FREEZE_MANIFEST.json").is_file())
            self.assertFalse(list(destination.parent.glob(destination.name + ".staging-*")))


if __name__ == "__main__":
    unittest.main()
