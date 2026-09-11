"""Fixed supplementary robustness analysis for the final Selective retriever.

The main RQ4 TEST is already frozen.  This script reuses that exact pipeline,
requires clean-result parity, applies only prespecified perturbations, performs
no selection or tuning, and labels the analysis as supplementary/post-hoc.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VERSION = "phase2_selective_robustness_v1"
HEADLINE = (
    "hit_at_1",
    "hit_at_3",
    "hit_at_5",
    "mrr",
    "ndcg_at_5",
    "macro_action_family_recall",
)


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


def verify_sha_manifest(directory: Path) -> None:
    sums = directory / "SHA256SUMS.txt"
    if not sums.is_file():
        raise RuntimeError(f"Missing checksum manifest: {sums}")
    for line in sums.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split("  ", 1)
        target = directory / Path(relative)
        if not target.is_file() or sha256(target) != expected:
            raise RuntimeError(f"Frozen checksum mismatch: {target}")


def truncate(text: str, fraction: float) -> str:
    tokens = str(text).split()
    keep = max(1, round(len(tokens) * (1.0 - fraction)))
    return " ".join(tokens[:keep])


def spelling_noise(text: str, rate: float, seed: int) -> str:
    generator = random.Random(seed)
    characters = list(str(text))
    candidates = [index for index, character in enumerate(characters) if character.isalpha()]
    count = min(len(candidates), round(len(candidates) * rate))
    for index in generator.sample(candidates, count):
        if generator.random() < 0.5:
            characters[index] = ""
        else:
            base = ord("A") if characters[index].isupper() else ord("a")
            characters[index] = chr(base + ((ord(characters[index]) - base + 1) % 26))
    return "".join(characters)


def stable_seed(ident: str, condition: str, value: float) -> int:
    token = f"42|{ident}|{condition}|{value:.2f}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(token).digest()[:8], "big")


def perturb(frame: Any, kind: str, value: float) -> Any:
    changed = frame.copy(deep=True)
    if kind == "truncation":
        changed["problem_norm"] = changed["problem_norm"].map(lambda text: truncate(text, value))
    elif kind == "spelling_noise":
        changed["problem_norm"] = [
            spelling_noise(text, value, stable_seed(str(ident), kind, value))
            for ident, text in zip(changed["ident"], changed["problem_norm"], strict=False)
        ]
    elif kind == "missing_structure":
        for column in ("components", "faults", "problem_entity_types", "problem_relation_types"):
            changed[column] = [[] for _ in range(len(changed))]
    else:
        raise ValueError(f"Unsupported condition: {kind}")
    return changed


def close(left: float, right: float, tolerance: float = 1e-12) -> bool:
    return math.isclose(float(left), float(right), rel_tol=tolerance, abs_tol=tolerance)


def validate_clean_parity(observed: dict[str, Any], frozen_result: dict[str, Any]) -> None:
    expected = frozen_result["selected_configuration_metrics"]
    differences = {
        metric: {"expected": expected[metric], "observed": observed[metric]}
        for metric in HEADLINE
        if not close(observed[metric], expected[metric])
    }
    if differences:
        raise RuntimeError("Clean parity with frozen RQ4 failed: " + json.dumps(differences, sort_keys=True))


def run(repo: Path) -> Path:
    config_path = repo / "configs/experiments/phase2_selective_robustness_v1.json"
    config = read_json(config_path)
    target = repo / "outputs/frozen" / VERSION
    if target.exists():
        verify_sha_manifest(target)
        manifest = read_json(target / "FREEZE_MANIFEST.json")
        if manifest.get("status") != "complete" or manifest.get("version") != VERSION:
            raise RuntimeError(f"Existing robustness freeze is invalid: {target}")
        print(f"SELECTIVE_ROBUSTNESS_ALREADY_COMPLETE -> {target}")
        return target

    legacy = repo / "legacy_import/maintenance-ie/avimaint_dss"
    if not legacy.is_dir():
        raise RuntimeError(f"Missing final retrieval implementation: {legacy}")
    sys.path.insert(0, str(legacy))
    os.environ["AVIMAINT_DSS_ROOT"] = str(legacy)
    os.environ["AVIMAINT_SELECTIVE_OUTPUT_BASE"] = str(repo / "outputs")

    import selective_rq4_rq5_final as final  # type: ignore
    from core.retrieval import Retriever  # type: ignore

    mode, _internal, tau, aggregation = final.selected_configuration()
    selected = config["selected_configuration"]
    if mode != selected["retrieval_mode"] or not close(tau, selected["tau"]) or aggregation != selected["aggregation"]:
        raise RuntimeError(
            f"Frozen selection differs from the Phase 2 protocol: mode={mode}, tau={tau}, aggregation={aggregation}"
        )

    frame = final.load_evaluation_frame()
    train = frame[frame.frozen_split == "train"].reset_index(drop=True)
    test = frame[frame.frozen_split == "test"].reset_index(drop=True)
    if len(test) != int(config["expected_partition_records"]):
        raise RuntimeError(f"Expected 925 frozen TEST records, found {len(test)}")
    eligible = test[test.action_family != "Other"]
    if len(eligible) != int(config["expected_evaluable_queries"]):
        raise RuntimeError(f"Expected 828 evaluable TEST queries, found {len(eligible)}")

    retriever = Retriever(train)
    priors = final.cluster_family_priors(train)
    frozen_result_path = (
        repo / "outputs/frozen/final_rq4_rq5_selective_final/"
        "rq4_case_retrieval_selective_final/test/RQ4_FINAL_TEST.json"
    )
    frozen_result = read_json(frozen_result_path)

    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=VERSION + ".", dir=target.parent))
    try:
        predictions_dir = staging / "predictions"
        predictions_dir.mkdir()
        rows: list[dict[str, Any]] = []
        details: dict[str, Any] = {}
        clean_metrics: dict[str, Any] | None = None
        for condition in config["conditions"]:
            kind = str(condition["kind"])
            value = float(condition["value"])
            queries = test if kind == "clean" else perturb(test, kind, value)
            retrieved = final.retrieve_mode(retriever, queries, mode)
            metrics, predictions = final.score_retrieved(
                train, retrieved, priors, tau, aggregation, detailed=True
            )
            if int(metrics["queries"]) != int(config["expected_evaluable_queries"]):
                raise RuntimeError(f"Unexpected query count for {kind} {value}: {metrics['queries']}")
            if kind == "clean":
                validate_clean_parity(metrics, frozen_result)
                clean_metrics = metrics
            key = f"{kind}_{value:.2f}"
            predictions.to_csv(predictions_dir / f"predictions_{key}.csv", index=False)
            details[key] = metrics
            row = {"condition": kind, "value": value, "queries": int(metrics["queries"])}
            row.update({metric: float(metrics[metric]) for metric in HEADLINE})
            row["mean_top_score"] = float(predictions["top_score"].mean())
            row["mean_margin"] = float(predictions["margin"].mean())
            rows.append(row)

        if clean_metrics is None:
            raise RuntimeError("The robustness protocol has no clean condition.")
        clean_row = rows[0]
        for row in rows:
            for metric in HEADLINE:
                row[f"{metric}__absolute_drop"] = clean_row[metric] - row[metric]
                row[f"{metric}__relative_drop"] = (
                    (clean_row[metric] - row[metric]) / clean_row[metric] if clean_row[metric] else 0.0
                )

        fieldnames = list(rows[0])
        with (staging / "robustness_metrics.csv").open("w", encoding="utf-8", newline="") as sink:
            writer = csv.DictWriter(sink, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        write_json(staging / "robustness_metrics.json", details)
        shutil.copy2(config_path, staging / config_path.name)

        constant_metrics = [metric for metric in HEADLINE if len({row[metric] for row in rows}) == 1]
        report = [
            "# Final Selective retrieval robustness",
            "",
            "Classification: **supplementary post-hoc analysis with a locked protocol**. It must not be presented as a newly preregistered confirmatory RQ4 test.",
            "",
            "The analysis reuses the final Selective-ByT5 representation, the frozen TEST partition, the DEV-selected canonical BM25 mode, `tau = 0.15`, and cluster-expanded aggregation. No model was trained and no parameter was selected from these results.",
            "",
            "| Condition | Value | Hit@1 | Hit@3 | Hit@5 | MRR | nDCG@5 | Macro recall | Hit@1 drop |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for row in rows:
            report.append(
                f"| {row['condition']} | {row['value']:.2f} | {row['hit_at_1']:.6f} | "
                f"{row['hit_at_3']:.6f} | {row['hit_at_5']:.6f} | {row['mrr']:.6f} | "
                f"{row['ndcg_at_5']:.6f} | {row['macro_action_family_recall']:.6f} | "
                f"{row['hit_at_1__absolute_drop']:.6f} |"
            )
        report += [
            "",
            "Perturbations are channel-isolated: truncation and spelling noise change only normalized problem text; missing-structure removes structured features while retaining clean text.",
            "",
            "Historical action-family agreement is an evaluation proxy, not technical correctness or maintenance approval.",
            "",
        ]
        if constant_metrics:
            report += [
                "Metrics constant across all conditions: " + ", ".join(f"`{name}`" for name in constant_metrics) + ". Constant metrics should be described as invariant under this protocol, not as evidence of sensitivity.",
                "",
            ]
        (staging / "SELECTIVE_ROBUSTNESS_RESULTS.md").write_text("\n".join(report), encoding="utf-8")

        final_freeze_manifest = repo / "outputs/frozen/final_rq4_rq5_selective_final/FREEZE_MANIFEST.json"
        manifest = {
            "version": VERSION,
            "status": "complete",
            "created_utc": utc_now(),
            "classification": config["classification"],
            "representation": "selective_byt5",
            "partition": "frozen_test",
            "partition_records": len(test),
            "evaluable_queries": len(eligible),
            "selected_configuration": selected,
            "conditions": config["conditions"],
            "training_performed": False,
            "retuning_performed": False,
            "clean_parity_with_frozen_rq4": True,
            "constant_metrics": constant_metrics,
            "source_sha256": {
                str(Path(__file__).resolve().relative_to(repo)).replace("\\", "/"): sha256(Path(__file__).resolve()),
                str(config_path.relative_to(repo)).replace("\\", "/"): sha256(config_path),
                str(final_freeze_manifest.relative_to(repo)).replace("\\", "/"): sha256(final_freeze_manifest),
                str(frozen_result_path.relative_to(repo)).replace("\\", "/"): sha256(frozen_result_path),
            },
            "interpretation": "Historical action-family agreement only; not technical correctness or approval.",
        }
        write_json(staging / "FREEZE_MANIFEST.json", manifest)
        files = sorted(path for path in staging.rglob("*") if path.is_file())
        (staging / "SHA256SUMS.txt").write_text(
            "\n".join(f"{sha256(path)}  {path.relative_to(staging).as_posix()}" for path in files) + "\n",
            encoding="utf-8",
        )
        os.replace(staging, target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    verify_sha_manifest(target)
    print(f"SELECTIVE_ROBUSTNESS_COMPLETE -> {target}")
    return target


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        run(args.repo_root.resolve())
        return 0
    except Exception as exc:
        print(f"SELECTIVE_ROBUSTNESS_FAILED: {exc}", file=sys.stderr)
        return 12


if __name__ == "__main__":
    raise SystemExit(main())
