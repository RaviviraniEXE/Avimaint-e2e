"""Deterministic cross-cutting retrieval robustness study.

Evaluates lexical truncation, spelling noise, and missing structured evidence.
Multi-problem records are exported for qualitative review because a single
recorded action-family label is not a valid gold label for two joined problems.

Design note (channel isolation)
-------------------------------
`truncation` and `spelling_noise` degrade only the normalised problem text;
the structured evidence fields were extracted from the *clean* text and are
left intact. `missing_structure` does the reverse. Each condition therefore
isolates one input channel rather than simulating an end-to-end degradation.
This is deliberate and is reported as such.
"""

from __future__ import annotations

import argparse
import json
import random

import pandas as pd
from research_evaluation import PROJECT_ROOT, evaluate_partition, load_system, protocol_frames

# Summary metrics for which a drop-versus-clean column is emitted.
DROP_METRICS = [
    "top1_action_family_agreement",
    "top3_action_family_agreement",
    "mrr",
    "ndcg_at_3",
    "macro_action_family_recall",
]


def truncate(text: str, fraction: float) -> str:
    tokens = str(text).split()
    keep = max(1, round(len(tokens) * (1.0 - fraction)))
    return " ".join(tokens[:keep])


def spelling_noise(text: str, rate: float, seed: int) -> str:
    rng = random.Random(seed)
    chars = list(str(text))
    candidates = [i for i, char in enumerate(chars) if char.isalpha()]
    for index in rng.sample(candidates, min(len(candidates), round(len(candidates) * rate))):
        if rng.random() < 0.5:
            chars[index] = ""
        else:
            base = ord("A") if chars[index].isupper() else ord("a")
            chars[index] = chr(base + ((ord(chars[index]) - base + 1) % 26))
    return "".join(chars)


def perturb(frame: pd.DataFrame, kind: str, value: float) -> pd.DataFrame:
    changed = frame.copy(deep=True)
    if kind == "truncation":
        changed["problem_norm"] = changed["problem_norm"].map(lambda text: truncate(text, value))
    elif kind == "spelling_noise":
        changed["problem_norm"] = [
            spelling_noise(text, value, 42000 + i) for i, text in enumerate(changed["problem_norm"])
        ]
    elif kind == "missing_structure":
        changed["components"] = [[] for _ in range(len(changed))]
        changed["faults"] = [[] for _ in range(len(changed))]
        changed["problem_entity_types"] = [[] for _ in range(len(changed))]
        changed["problem_relation_types"] = [[] for _ in range(len(changed))]
    else:
        raise ValueError(kind)
    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--system", choices=["raw", "rules_then_byt5"], default="rules_then_byt5")
    parser.add_argument(
        "--representation", choices=["bm25", "tfidf", "structure", "hybrid"], default="hybrid"
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="Smoke-test limit; use 0 for the thesis run"
    )
    args = parser.parse_args()
    frame = load_system(args.system)
    candidates, clean_queries = protocol_frames(frame, "frozen", "test")
    if args.limit:
        clean_queries = clean_queries.head(args.limit)

    # Population audit: the robustness study must run on the same frozen
    # partition that the main retrieval results are reported on.
    print(
        f"[population] system={args.system} representation={args.representation} "
        f"queries={len(clean_queries)} candidates={len(candidates)}"
    )
    if "action_family" in candidates.columns:
        print("[population] candidate action_family distribution:")
        print(candidates["action_family"].value_counts(dropna=False).to_string())

    conditions = [
        ("clean", 0.0),
        ("truncation", 0.10),
        ("truncation", 0.20),
        ("truncation", 0.30),
        ("spelling_noise", 0.05),
        ("spelling_noise", 0.10),
        ("missing_structure", 1.0),
    ]

    # Each (system, representation) pair writes to its own folder so that a
    # second run does not silently overwrite the first.
    output = (
        PROJECT_ROOT
        / "outputs/runs/crosscut_robustness"
        / f"retrieval__{args.system}__{args.representation}"
    )
    output.mkdir(parents=True, exist_ok=True)

    rows = []
    clean_ranks = None
    for kind, value in conditions:
        queries = clean_queries if kind == "clean" else perturb(clean_queries, kind, value)
        metrics, predictions = evaluate_partition(candidates, queries, args.representation)

        # Per-condition scalars that are only visible in the prediction frame.
        row = {"condition": kind, "value": value}
        row.update({k: v for k, v in metrics.items() if not isinstance(v, dict)})
        for column, label in [
            ("top_score", "mean_top_score"),
            ("top1_top2_margin", "mean_top1_top2_margin"),
            ("lexical_structure_agreement", "mean_lexical_structure_agreement"),
            ("extracted_information_coverage", "mean_extracted_information_coverage"),
        ]:
            if column in predictions.columns:
                row[label] = float(predictions[column].mean())

        ranks = predictions.set_index("ident")["family_rank"]
        if kind == "clean":
            clean_ranks = ranks
            row["family_rank_changed_fraction"] = 0.0
        else:
            aligned = ranks.reindex(clean_ranks.index)
            row["family_rank_changed_fraction"] = float((aligned != clean_ranks).mean())

        rows.append(row)
        predictions.to_csv(output / f"predictions_{kind}_{value:.2f}.csv", index=False)

    summary = pd.DataFrame(rows)

    # Drop columns for every headline metric, not top-1 alone.
    for metric in DROP_METRICS:
        if metric in summary.columns:
            summary[f"{metric}__absolute_drop"] = float(summary.iloc[0][metric]) - summary[metric]
    # Backwards-compatible name used by the earlier run.
    if "top1_action_family_agreement" in summary.columns:
        summary["top1_absolute_drop"] = summary["top1_action_family_agreement__absolute_drop"]

    summary.to_csv(output / "robustness_metrics.csv", index=False)

    # Saturation guard: a metric that is constant across all seven conditions
    # carries no robustness information and must not be reported as a result.
    saturated = [m for m in DROP_METRICS if m in summary.columns and summary[m].nunique() == 1]
    if saturated:
        print("\n[WARNING] constant across all conditions, not usable as a robustness metric:")
        for metric in saturated:
            print(f"  {metric} = {summary.iloc[0][metric]:.6f}")
        clean_predictions = pd.read_csv(output / "predictions_clean_0.00.csv")
        if "predicted_family" in clean_predictions.columns:
            counts = clean_predictions["predicted_family"].value_counts(dropna=False)
            print("  clean predicted_family distribution:")
            print("  " + counts.to_string().replace("\n", "\n  "))
            if len(counts) == 1:
                print(
                    "  -> the predictor emits a single class; top-1 agreement is the "
                    "majority-class rate, not a retrieval result."
                )

    qualitative = clean_queries.reset_index(drop=True).head(50).copy()
    if len(qualitative) > 1:
        paired = pd.DataFrame(
            {
                "first_ident": qualitative["ident"].iloc[::2].reset_index(drop=True),
                "first_problem": qualitative["problem"].iloc[::2].reset_index(drop=True),
                "second_ident": qualitative["ident"].iloc[1::2].reset_index(drop=True),
                "second_problem": qualitative["problem"].iloc[1::2].reset_index(drop=True),
            }
        ).dropna()
        paired["combined_problem"] = paired["first_problem"] + " ; " + paired["second_problem"]
        paired["evaluation_status"] = "qualitative_only_no_single_valid_action_family_gold"
        paired.to_csv(output / "multi_problem_qualitative_set.csv", index=False)

    metadata = {
        "seed": 42,
        "protocol": "frozen_train_candidates_frozen_test_queries",
        "system": args.system,
        "representation": args.representation,
        "queries": int(len(clean_queries)),
        "candidate_cases": int(len(candidates)),
        "conditions": [{"kind": k, "value": v} for k, v in conditions],
        "channel_isolation": (
            "truncation and spelling_noise degrade the problem text only; "
            "structured fields remain those extracted from the clean text. "
            "missing_structure degrades the structured fields only."
        ),
        "multi_problem_policy": "qualitative only; no misleading single-label accuracy",
        "saturated_metrics": saturated,
    }
    (output / "run_metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nRobustness study -> {output}")


if __name__ == "__main__":
    main()