from __future__ import annotations

import csv
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
import random
import shutil
import sys
from pathlib import Path
from typing import Any

try:
    from .common import atomic_json, atomic_text, repo_root, sha256, verify_checksum_manifest, write_checksum_manifest
except ImportError:
    from common import atomic_json, atomic_text, repo_root, sha256, verify_checksum_manifest, write_checksum_manifest


CONDITIONS = (
    ("clean", 0.00),
    ("truncation", 0.10),
    ("truncation", 0.20),
    ("truncation", 0.30),
    ("spelling_noise", 0.05),
    ("spelling_noise", 0.10),
    ("missing_structure", 1.00),
)
METRICS = (
    "hit_at_1",
    "hit_at_3",
    "hit_at_5",
    "mrr",
    "ndcg_at_5",
    "macro_action_family_recall",
    "answer_rate",
)
EXPECTED_CONFIGURATION = {
    "public_mode": "selective_canonical_bm25",
    "internal_mode": "norm_bm25",
    "tau": 0.15,
    "aggregation": "cluster_expanded",
}
EXPECTED_QUERIES = 828


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def load_final_module(root: Path):
    source = root / "legacy_import" / "maintenance-ie" / "avimaint_dss" / "selective_rq4_rq5_final.py"
    if not source.is_file():
        raise RuntimeError(f"Final Selective RQ4/RQ5 implementation is missing: {source}")
    dashboard = source.parent
    if str(dashboard) not in sys.path:
        sys.path.insert(0, str(dashboard))
    spec = importlib.util.spec_from_file_location("avimaint_selective_final_phase2", source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not import {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, source


def truncate(text: str, fraction: float) -> str:
    tokens = str(text).split()
    if not tokens:
        return ""
    keep = max(1, int(round(len(tokens) * (1.0 - fraction))))
    return " ".join(tokens[:keep])


def spelling_noise(text: str, rate: float, ident: str, seed: int = 42) -> str:
    chars = list(str(text))
    candidates = [index for index, char in enumerate(chars) if char.isalpha()]
    count = min(len(candidates), int(round(len(candidates) * rate)))
    stable = hashlib.sha256(f"{seed}|{ident}|{rate:.4f}".encode("utf-8")).digest()
    rng = random.Random(int.from_bytes(stable[:8], "big"))
    for index in rng.sample(candidates, count):
        if rng.random() < 0.5:
            chars[index] = ""
        else:
            base = ord("A") if chars[index].isupper() else ord("a")
            chars[index] = chr(base + ((ord(chars[index]) - base + 1) % 26))
    return "".join(chars)


def perturb(frame, kind: str, value: float):
    changed = frame.copy(deep=True)
    if kind == "clean":
        return changed
    if kind == "truncation":
        changed["problem_norm"] = changed["problem_norm"].map(lambda text: truncate(text, value))
    elif kind == "spelling_noise":
        changed["problem_norm"] = [
            spelling_noise(text, value, str(ident))
            for text, ident in zip(changed["problem_norm"], changed["ident"], strict=False)
        ]
    elif kind == "missing_structure":
        for column in ("components", "faults", "problem_entity_types", "problem_relation_types"):
            changed[column] = [[] for _ in range(len(changed))]
    else:
        raise ValueError(f"Unknown robustness condition: {kind}")
    return changed


def compare_clean_metrics(actual: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    failures: dict[str, dict[str, float]] = {}
    for name in METRICS:
        left = float(actual[name])
        right = float(expected[name])
        if not math.isclose(left, right, rel_tol=0.0, abs_tol=1e-12):
            failures[name] = {"actual": left, "expected": right}
    if int(actual.get("queries", -1)) != int(expected.get("queries", -2)):
        failures["queries"] = {
            "actual": float(actual.get("queries", -1)),
            "expected": float(expected.get("queries", -2)),
        }
    if failures:
        raise RuntimeError("Clean robustness condition does not reproduce frozen RQ4: " + json.dumps(failures))
    return {"passed": True, "absolute_tolerance": 1e-12, "metrics_checked": list(METRICS) + ["queries"]}


def verify_existing(output: Path, expected_identity: dict[str, Any]) -> bool:
    if not output.exists():
        return False
    manifest_path = output / "RUN_MANIFEST.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"Existing robustness directory is incomplete; move it aside for audit: {output}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("input_identity") != expected_identity:
        raise RuntimeError(f"Existing robustness results belong to different inputs: {output}")
    verify_checksum_manifest(output)
    if not manifest.get("clean_parity", {}).get("passed"):
        raise RuntimeError("Existing robustness result did not pass clean-result parity.")
    print(f"REUSE verified robustness result: {output}")
    return True


def recover_verified_staging(stage: Path, output: Path, expected_identity: dict[str, Any]) -> bool:
    """Promote a fully verified staging directory left by an interrupted final move."""
    if not stage.exists():
        return False
    if not verify_existing(stage, expected_identity):
        return False
    os.replace(stage, output)
    print(f"RECOVERED verified staged robustness result: {output}")
    return True


def write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "condition", "value", "queries", *METRICS,
        *[f"{metric}_absolute_drop" for metric in METRICS[:-1]],
        "top_family_changed_fraction", "true_family_rank_changed_fraction",
        "mean_support_clusters", "interpretation",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_thesis_report(path: Path, rows: list[dict[str, Any]], identity: dict[str, Any]) -> None:
    lines = [
        "# Supplementary fixed-protocol retrieval robustness",
        "",
        "This is a post-hoc robustness analysis using the already-frozen configuration. It performs no training, model selection, or retuning. The clean condition reproduces the frozen RQ4 result exactly. All scores measure agreement with the recorded historical action family, not technical correctness.",
        "",
        "- Representation: Selective ByT5",
        "- Retrieval: canonical BM25",
        "- Prior temperature: tau = 0.15",
        "- Aggregation: cluster-expanded",
        f"- Evaluable locked-test queries: {EXPECTED_QUERIES}",
        "- Perturbation seed: 42",
        "",
        "| Condition | Level | Hit@1 | Hit@3 | Hit@5 | MRR | nDCG@5 | Macro recall | Hit@1 drop | Top family changed |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {condition} | {value:.2f} | {hit_at_1:.4f} | {hit_at_3:.4f} | {hit_at_5:.4f} | "
            "{mrr:.4f} | {ndcg_at_5:.4f} | {macro_action_family_recall:.4f} | "
            "{hit_at_1_absolute_drop:.4f} | {top_family_changed_fraction:.4f} |".format(**row)
        )
    lines.extend([
        "",
        "## Interpretation boundary",
        "",
        "Truncation and spelling noise modify only the canonical problem-text retrieval channel; the structured fields remain those extracted from the clean query. The missing-structure condition is a negative control for the selected canonical-BM25 mode and is therefore expected not to change its ranking. Joined multi-problem queries are not assigned a misleading single action-family gold label and are outside this quantitative analysis.",
        "",
        "## Frozen input identity",
        "",
        f"- Final RQ4 result SHA-256: `{identity['rq4_final_test_sha256']}`",
        f"- Final RQ4/RQ5 freeze manifest SHA-256: `{identity['rq4_freeze_manifest_sha256']}`",
        f"- Selective implementation SHA-256: `{identity['implementation_sha256']}`",
        "",
    ])
    atomic_text(path, "\n".join(lines))


def main() -> int:
    try:
        root = repo_root()
        module, implementation = load_final_module(root)
        final_test = root / "outputs" / "frozen" / "final_rq4_rq5_selective_final" / "rq4_case_retrieval_selective_final" / "test" / "RQ4_FINAL_TEST.json"
        freeze_manifest = root / "outputs" / "frozen" / "final_rq4_rq5_selective_final" / "FREEZE_MANIFEST.json"
        freeze_sums = root / "outputs" / "frozen" / "final_rq4_rq5_selective_final" / "SHA256SUMS.txt"
        for path in (final_test, freeze_manifest, freeze_sums):
            if not path.is_file():
                raise RuntimeError(f"Required frozen RQ4/RQ5 artifact is missing: {path}")
        module.command_verify(type("Args", (), {})())
        result = json.loads(final_test.read_text(encoding="utf-8"))
        public_mode = str(result.get("selected_mode"))
        internal_mode = str(result.get("internal_mode"))
        tau = float(result.get("selected_tau"))
        aggregation = str(result.get("selected_aggregation"))
        actual_configuration = {
            "public_mode": public_mode,
            "internal_mode": internal_mode,
            "tau": tau,
            "aggregation": aggregation,
        }
        if actual_configuration != EXPECTED_CONFIGURATION:
            raise RuntimeError(f"Frozen selected configuration changed: {actual_configuration}")
        identity = {
            "rq4_final_test_sha256": sha256(final_test),
            "rq4_freeze_manifest_sha256": sha256(freeze_manifest),
            "rq4_freeze_sums_sha256": sha256(freeze_sums),
            "implementation_sha256": sha256(implementation),
            "run_identity": result.get("run_identity"),
            "selected_configuration": actual_configuration,
            "conditions": [{"condition": kind, "value": value} for kind, value in CONDITIONS],
        }
        output = root / "outputs" / "runs" / "phase2_final_protocol_robustness"
        if verify_existing(output, identity):
            return 0

        stage = output.with_name(output.name + ".staging")
        if recover_verified_staging(stage, output, identity):
            return 0

        frame = module.load_evaluation_frame()
        train = frame[frame.frozen_split == "train"].reset_index(drop=True)
        clean_queries = frame[frame.frozen_split == "test"].reset_index(drop=True)
        priors = module.cluster_family_priors(train)
        from core.retrieval import Retriever
        retriever = Retriever(train)

        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(parents=True)
        rows: list[dict[str, Any]] = []
        clean_predictions = None
        clean_metrics = None
        for kind, value in CONDITIONS:
            queries = perturb(clean_queries, kind, value)
            retrieved = module.retrieve_mode(retriever, queries, public_mode)
            metrics, predictions = module.score_retrieved(
                train, retrieved, priors, tau, aggregation, detailed=False
            )
            if int(metrics["queries"]) != EXPECTED_QUERIES:
                raise RuntimeError(f"Expected {EXPECTED_QUERIES} evaluable queries; found {metrics['queries']} for {kind} {value}.")
            indexed_queries = queries.copy()
            indexed_queries.index = indexed_queries["ident"].astype(str)
            query_text = indexed_queries["problem_norm"]
            predictions["perturbed_problem_norm"] = predictions["ident"].astype(str).map(query_text)
            if predictions["perturbed_problem_norm"].isna().any():
                raise RuntimeError(f"Could not map perturbed query text for {kind} {value}.")
            if clean_metrics is None:
                clean_metrics = metrics
                clean_predictions = predictions.set_index("ident")
                clean_parity = compare_clean_metrics(metrics, result["selected_configuration_metrics"])
            aligned = predictions.set_index("ident").reindex(clean_predictions.index)
            row = {"condition": kind, "value": value, **{name: float(metrics[name]) for name in METRICS}}
            row["queries"] = int(metrics["queries"])
            for name in METRICS[:-1]:
                row[f"{name}_absolute_drop"] = float(clean_metrics[name]) - float(metrics[name])
            row["top_family_changed_fraction"] = float((aligned["predicted_family"] != clean_predictions["predicted_family"]).mean())
            row["true_family_rank_changed_fraction"] = float((aligned["rank"] != clean_predictions["rank"]).mean())
            row["mean_support_clusters"] = float(predictions["support_clusters"].mean())
            row["interpretation"] = "historical action-family agreement; not technical correctness"
            rows.append(row)
            predictions.to_csv(stage / f"predictions_{kind}_{value:.2f}.csv", index=False)
            print(kind, value, json.dumps({name: row[name] for name in ("hit_at_1", "hit_at_3", "mrr", "macro_action_family_recall", "top_family_changed_fraction")}), flush=True)

        write_summary_csv(stage / "robustness_metrics.csv", rows)
        write_thesis_report(stage / "ROBUSTNESS_THESIS_RESULTS.md", rows, identity)
        manifest = {
            "version": "phase2_final_protocol_robustness_v1",
            "created_utc": utc_now(),
            "status": "complete",
            "supplementary_post_hoc_fixed_protocol": True,
            "training_performed": False,
            "selection_or_retuning_performed": False,
            "representation": "selective_byt5",
            "configuration": actual_configuration,
            "population": {"partition": "locked_test", "evaluable_queries": EXPECTED_QUERIES},
            "seed": 42,
            "channel_isolation": "Truncation and spelling noise modify canonical problem text only; missing_structure removes structured fields only.",
            "missing_structure_role": "negative control because the selected canonical-BM25 mode does not use structured fields",
            "clean_parity": clean_parity,
            "interpretation": "Historical action-family agreement only; not technical correctness, safety, or regulatory approval.",
            "input_identity": identity,
        }
        atomic_json(stage / "RUN_MANIFEST.json", manifest)
        write_checksum_manifest(stage)
        verify_checksum_manifest(stage)
        os.replace(stage, output)
        print(f"PHASE2_FINAL_PROTOCOL_ROBUSTNESS_COMPLETE {output}")
        return 0
    except (RuntimeError, ValueError, KeyError, json.JSONDecodeError, ImportError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
