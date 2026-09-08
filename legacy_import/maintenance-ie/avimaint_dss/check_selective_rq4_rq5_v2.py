from __future__ import annotations

import importlib.util
import inspect
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("selective_v2", ROOT / "selective_rq4_rq5_v2.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def hit(index: int, score: float):
    return SimpleNamespace(
        idx=index,
        score=score,
        text_sim=score,
        struct=score,
        channels={"char": score, "struct": score},
    )


def main() -> None:
    assert MODULE.VERSION == "selective_rq4_rq5_v2"
    assert MODULE.OPERATIONAL_AGGREGATION == "cluster_expanded"
    assert MODULE.canonical_problem_key("#2 INTAKES LEAKING") == "num_2 intake leaking"
    assert MODULE.canonical_problem_key("NUMBER TWO INTAKE LEAKING") == "num_2 intake leaking"
    assert MODULE.canonical_component_v2("intakes") == "intake"
    # The `spert` environment is deliberately lean. Precompute must use the
    # standard-library CSV reader and must not require pandas.
    assert "load_csv" not in inspect.getsource(MODULE.command_precompute)
    assert "load_csv" not in inspect.getsource(MODULE.validate_prediction_file)
    assert "import pandas" not in inspect.getsource(MODULE.load_prediction_input_rows)

    candidates = pd.DataFrame([
        {"ident": "1", "problem": "NUMBER TWO INTAKE LEAKING", "problem_raw": "#2 INTAKE LEAKING", "problem_norm": "num_2 intake leaking", "action": "REPLACED GASKET", "action_raw": "R&R GASKET", "action_family": "Replace", "outcome": "unknown", "cluster_id": "C1", "components": ["intake"], "faults": ["leak"]},
        {"ident": "2", "problem": "NUMBER TWO INTAKE LEAKING", "problem_raw": "#2 INTAKE LEAKING", "problem_norm": "num_2 intake leaking", "action": "PERFORMED LEAK CHECK", "action_raw": "LEAK CK", "action_family": "Diagnose", "outcome": "positive", "cluster_id": "C1", "components": ["intakes"], "faults": ["leak"]},
        {"ident": "3", "problem": "INTAKE LEAK", "problem_raw": "INTAKE LEAK", "problem_norm": "intake leak", "action": "REPAIR FAILED", "action_raw": "REPAIR FAILED", "action_family": "Repair", "outcome": "negative", "cluster_id": "C2", "components": ["intake"], "faults": ["leak"]},
        {"ident": "4", "problem": "INTAKE LEAK", "problem_raw": "INTAKE LEAK", "problem_norm": "intake leak", "action": "SERVICED INTAKE", "action_raw": "SERVICED INTAKE", "action_family": "Service", "outcome": "unknown", "cluster_id": "C3", "components": ["intake"], "faults": ["leak"]},
    ])
    query = SimpleNamespace(problem_norm="num_2 intake leaking", components=["intake"], faults=["leak"])
    priors = MODULE.cluster_family_priors(candidates)
    assert "Repair" not in priors
    assert set(priors) == {"Replace", "Diagnose", "Service"}
    assert abs(sum(priors.values()) - 1.0) < 1e-12

    base_hits = [hit(0, 0.9), hit(2, 0.7), hit(3, 0.6)]
    representative = MODULE.aggregate_action_evidence(candidates, base_hits, priors, 0.0, "representative_only", query)
    expanded = MODULE.aggregate_action_evidence(candidates, base_hits, priors, 0.0, MODULE.OPERATIONAL_AGGREGATION, query)
    assert "Diagnose" not in [row["family"] for row in representative["families"]]
    assert "Diagnose" in [row["family"] for row in expanded["families"]]
    assert all(row["support_clusters"] == 1 for row in expanded["families"])
    assert expanded["evidence_tier"] == "limited"
    assert [row["ident"] for row in expanded["negative_or_mixed"]] == ["3"]
    assert any(row["pattern_key"] == "Diagnose|intake|leak" for row in expanded["patterns"])
    rung, _label = MODULE.evidence_rung(candidates, base_hits, query)
    assert rung == "A"

    scored_query = SimpleNamespace(
        ident="Q1", leakage_group_id="QG", problem="NUMBER TWO INTAKE LEAKING",
        problem_raw="#2 INTAKE LEAKING", problem_norm="num_2 intake leaking",
        components=["intake"], faults=["leak"], action_family="Diagnose",
        action_families=["Replace", "Diagnose"],
    )
    metrics, predictions = MODULE.score_retrieved(
        candidates, [(scored_query, base_hits)], priors, 0.0,
        MODULE.OPERATIONAL_AGGREGATION, detailed=True,
    )
    assert metrics["answer_rate"] == 1.0
    assert metrics["recorded_multi_family_set_recall_at_3"] == 1.0
    assert predictions.iloc[0].evidence_tier == "limited"
    assert "Diagnose" in predictions.iloc[0].ranked_families_json

    with tempfile.TemporaryDirectory() as name:
        directory = Path(name)
        sample = directory / "sample.txt"
        sample.write_text("frozen\n", encoding="utf-8")
        (directory / "SHA256SUMS.txt").write_text(
            f"{MODULE.sha256(sample)}  sample.txt\n", encoding="ascii"
        )
        report = MODULE.verify_checksum_manifest(directory)
        assert report["files_checked"] == 1

        jsonl = directory / "resume.jsonl"
        jsonl.write_text('{"complete": 1}\n{"partial":', encoding="utf-8")
        assert MODULE.repair_truncated_jsonl_tail(jsonl)
        assert jsonl.read_text(encoding="utf-8") == '{"complete": 1}\n'
        assert (directory / "resume.jsonl.truncated-tail-backup.txt").is_file()

        corrupt = directory / "corrupt.jsonl"
        corrupt.write_text('{"broken":\n{"complete": 2}\n', encoding="utf-8")
        try:
            MODULE.repair_truncated_jsonl_tail(corrupt)
        except RuntimeError as exc:
            assert "before its final line" in str(exc)
        else:
            raise AssertionError("Mid-file JSONL corruption must fail closed.")

    policy = {
        "tau_grid": MODULE.TAU_GRID,
        "margin": MODULE.HIT_NONINFERIORITY_MARGIN,
        "single_support": "visible",
    }
    print(json.dumps(policy, indent=2))
    print("SELECTIVE_RQ4_RQ5_V2_TESTS_OK")


if __name__ == "__main__":
    main()
