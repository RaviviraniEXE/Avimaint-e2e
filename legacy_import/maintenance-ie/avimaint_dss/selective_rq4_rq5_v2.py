"""Selective-ByT5 RQ4/RQ5 evaluation pipeline for AviMaint-DSS.

This is a versioned, inference-only migration.  It never modifies the frozen
raw RQ4/RQ5 package and never trains or retunes ByT5 or SpERT.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


VERSION = "selective_rq4_rq5_v2"
EXPECTED_RECORDS = 6169
NEAR_DUPLICATE_THRESHOLD = 0.87
TOP_K = 50
PRIOR_ALPHA = 1.0
HIT_NONINFERIORITY_MARGIN = 0.01
TAU_GRID = (0.00, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50)
OPERATIONAL_AGGREGATION = "cluster_expanded"
PUBLIC_MODES = {
    "selective_surface_bm25": "raw_bm25",
    "selective_canonical_bm25": "norm_bm25",
    "selective_tfidf": "norm_tfidf",
    "structure": "structure",
    "weighted_hybrid": "weighted_hybrid",
    "rrf_hybrid": "rrf_hybrid",
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def stable_id(prefix: str, text: str) -> str:
    return prefix + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def atomic_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    os.close(handle)
    temp = Path(name)
    try:
        temp.write_text(text, encoding=encoding)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def normalized_windows_relative(value: str) -> Path:
    return Path(str(value).replace("\\", os.sep).replace("/", os.sep))


def dashboard_root() -> Path:
    override = os.getenv("AVIMAINT_DSS_ROOT", "").strip()
    return Path(override).expanduser().resolve() if override else Path(__file__).resolve().parent


def paths() -> dict[str, Path]:
    root = dashboard_root()
    repo = root.parents[2]
    output_base_raw = os.getenv("AVIMAINT_SELECTIVE_OUTPUT_BASE", "").strip()
    output_base = Path(output_base_raw).expanduser().resolve() if output_base_raw else repo / "outputs"
    run = output_base / "runs" / "rq4_case_retrieval_selective_v2"
    rq5 = output_base / "runs" / "rq5_planning_support_selective_v2"
    return {
        "root": root,
        "repo": repo,
        "project": root.parent,
        "output_base": output_base,
        "source": repo / "outputs" / "normalization" / "full_corpus" / "selective_byt5.csv",
        "raw": root / "data" / "Aircraft_Annotation_DataFile.csv",
        "registry": root.parent / "outputs" / "reports" / "normalization_spert_matched_v2" / "MODEL_REGISTRY_V2.json",
        "operational_manifest": repo / "outputs" / "frozen" / "final_operational_ie_kg" / "extraction" / "FINAL_FULL_CORPUS_SPERT_MANIFEST.json",
        "operational_prep_manifest": repo / "outputs" / "frozen" / "final_operational_ie_kg" / "extraction" / "full_corpus_manifest.json",
        "raw_freeze": repo / "outputs" / "frozen" / "final_rq4_rq5",
        "run": run,
        "protocol": run / "protocol",
        "cases": run / "protocol" / "selective_cases_v2.csv",
        "protocol_json": run / "protocol" / "split_selective_v2.json",
        "preregistered": run / "protocol" / "PREREGISTERED_SELECTION_POLICY.json",
        "audit": run / "protocol" / "SELECTIVE_DATA_AUDIT.json",
        "pred_dir": run / "problem_only_spert",
        "predictions": run / "problem_only_spert" / "predictions_problem_only_selective.jsonl",
        "pred_manifest": run / "problem_only_spert" / "PREDICTION_MANIFEST.json",
        "dev": run / "dev",
        "test": run / "test",
        "test_lock": run / "FINAL_TEST_LOCK.json",
        "manual": run / "manual_review",
        "rq5": rq5,
        "frozen_index": repo / "outputs" / "frozen" / "final_operational_ie_kg" / "extraction" / "full_index.jsonl",
        "frozen": output_base / "frozen" / "final_rq4_rq5_selective_v2",
    }


NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
}
_NUMBER_ALT = "|".join(NUMBER_WORDS)


def canonical_problem_key(text: str) -> str:
    """Symmetric retrieval key; display text and SpERT offsets are untouched."""
    s = unicodedata.normalize("NFKC", str(text or "")).lower()
    s = re.sub(r"(?<!\d)(\d+)\s*/\s*(\d+)(?!\d)", r" ratio_\1_\2 ", s)
    s = re.sub(r"#\s*(\d+)\b", r" num_\1 ", s)
    s = re.sub(r"\b(?:no\.?|number)\s*(\d+)\b", r" num_\1 ", s)

    def word_number(match: re.Match[str]) -> str:
        return f" num_{NUMBER_WORDS[match.group(1)]} "

    s = re.sub(rf"\bnumber\s+({_NUMBER_ALT})\b", word_number, s)
    s = re.sub(r"\b(?:l\s*/\s*h|left[ -]?hand)\b", " left ", s)
    s = re.sub(r"\b(?:r\s*/\s*h|right[ -]?hand)\b", " right ", s)
    s = re.sub(r"\bfwd\b", " forward ", s)
    s = re.sub(r"\baft\b", " rear ", s)
    aliases = {
        "cyls": "cylinder", "cylinders": "cylinder", "cyl": "cylinder",
        "intakes": "intake", "gaskets": "gasket", "magnetos": "magneto",
        "mags": "magneto", "baffles": "baffle",
    }
    for source, target in aliases.items():
        s = re.sub(rf"\b{re.escape(source)}\b", target, s)
    s = re.sub(r"[^a-z0-9_]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def load_csv(path: Path):
    import pandas as pd
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def load_prediction_input_rows(path: Path) -> list[tuple[str, str]]:
    """Read the two precompute columns without requiring pandas in SpERT."""
    require_files([path])
    rows: list[tuple[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"IDENT", "problem_normalized"}
        missing = sorted(required - set(reader.fieldnames or []))
        if missing:
            raise RuntimeError(f"Prepared cases are missing precompute columns: {missing}")
        for line_no, row in enumerate(reader, 2):
            ident = str(row.get("IDENT") or "").strip()
            problem = str(row.get("problem_normalized") or "").strip()
            if not ident or not problem:
                raise RuntimeError(f"Empty IDENT/problem_normalized in prepared cases at CSV line {line_no}.")
            rows.append((ident, problem))
    if len(rows) != EXPECTED_RECORDS:
        raise RuntimeError(f"Expected {EXPECTED_RECORDS} prepared prediction rows; found {len(rows)}.")
    if len({ident for ident, _problem in rows}) != len(rows):
        raise RuntimeError("Prepared prediction input contains duplicate identifiers.")
    return rows


def require_files(items: Iterable[Path]) -> None:
    missing = [str(path) for path in items if not path.is_file()]
    if missing:
        raise RuntimeError("Required files are missing:\n  - " + "\n  - ".join(missing))


def verify_checksum_manifest(directory: Path) -> dict[str, Any]:
    sums = directory / "SHA256SUMS.txt"
    require_files([sums])
    failures = []
    checked = 0
    for line in sums.read_text(encoding="ascii").splitlines():
        if not line.strip():
            continue
        try:
            expected, relative = line.split("  ", 1)
        except ValueError as exc:
            raise RuntimeError(f"Malformed checksum line in {sums}: {line!r}") from exc
        target = directory / Path(relative)
        checked += 1
        if not target.is_file() or sha256(target).lower() != expected.lower():
            failures.append(relative)
    if failures:
        raise RuntimeError(
            f"Checksum verification failed in {directory}: " + ", ".join(failures[:10])
        )
    return {"directory": str(directory), "files_checked": checked, "sha256sums_sha256": sha256(sums)}


def resolve_model_identity(*, require_weights: bool = True) -> dict[str, Any]:
    p = paths()
    require_files([p["registry"], p["operational_manifest"], p["operational_prep_manifest"]])
    registry = json.loads(p["registry"].read_text(encoding="utf-8"))
    selected = registry.get("selective_byt5") or {}
    relative = str(selected.get("final_model_path") or "").strip()
    if not relative:
        raise RuntimeError("MODEL_REGISTRY_V2.json has no selective_byt5 final_model_path.")
    model = (p["repo"] / normalized_windows_relative(relative)).resolve()
    types = p["project"] / "outputs" / "spert_normalized" / "selective_byt5" / "avimaint_types.json"
    operational = json.loads(p["operational_manifest"].read_text(encoding="utf-8"))
    prep = json.loads(p["operational_prep_manifest"].read_text(encoding="utf-8"))
    if operational.get("representation") != "selective_byt5":
        raise RuntimeError("Frozen operational manifest is not selective_byt5.")
    if prep.get("representation") != "selective_byt5":
        raise RuntimeError("Frozen preparation manifest is not selective_byt5.")
    expected_weight = str((operational.get("model") or {}).get("weights_sha256") or "").lower()
    expected_types = str((operational.get("artifacts") or {}).get("types_sha256") or "").lower()
    expected_source = str(prep.get("representation_source_sha256") or "").lower()
    weight = model / "model.safetensors"
    if not weight.is_file():
        weight = model / "pytorch_model.bin"
    if require_weights:
        require_files([weight, types, p["source"]])
        actual_weight, actual_types = sha256(weight), sha256(types)
        if actual_weight.lower() != expected_weight:
            raise RuntimeError(f"Selective SpERT weight SHA mismatch: expected={expected_weight}, actual={actual_weight}")
        if actual_types.lower() != expected_types:
            raise RuntimeError(f"Selective SpERT type SHA mismatch: expected={expected_types}, actual={actual_types}")
    return {
        "model_path": str(model),
        "weight_path": str(weight),
        "weight_sha256": expected_weight,
        "types_path": str(types.resolve()),
        "types_sha256": expected_types,
        "manifest_source_sha256": expected_source,
        "installed_source_sha256": sha256(p["source"]) if p["source"].is_file() else "",
        "registry_sha256": sha256(p["registry"]),
        "operational_manifest_sha256": sha256(p["operational_manifest"]),
    }


def validate_source_alignment() -> dict[str, Any]:
    p = paths()
    require_files([p["source"], p["raw"], p["operational_prep_manifest"], p["frozen_index"]])
    source = load_csv(p["source"])
    raw = load_csv(p["raw"])
    required = {
        "record_id", "system", "problem_raw", "action_raw",
        "problem_normalized", "action_normalized", "problem_fallback",
        "action_fallback", "protected_tokens_preserved",
    }
    missing = sorted(required - set(source.columns))
    if missing:
        raise RuntimeError(f"selective_byt5.csv is missing columns: {missing}")
    if len(source) != EXPECTED_RECORDS or len(raw) != EXPECTED_RECORDS:
        raise RuntimeError(f"Expected {EXPECTED_RECORDS} records; selective={len(source)}, raw={len(raw)}")
    source["record_id"] = source["record_id"].astype(str)
    raw["IDENT"] = raw["IDENT"].astype(str)
    if source["record_id"].duplicated().any() or raw["IDENT"].duplicated().any():
        raise RuntimeError("Duplicate identifiers found in source data.")
    if set(source["record_id"]) != set(raw["IDENT"]):
        raise RuntimeError("Selective and raw identifier sets differ.")
    aligned = source.set_index("record_id").loc[raw["IDENT"]].reset_index()
    problem_mismatch = int((aligned["problem_raw"].astype(str).str.rstrip().to_numpy() != raw["PROBLEM"].astype(str).str.rstrip().to_numpy()).sum())
    action_mismatch = int((aligned["action_raw"].astype(str).str.rstrip().to_numpy() != raw["ACTION"].astype(str).str.rstrip().to_numpy()).sum())
    if problem_mismatch or action_mismatch:
        raise RuntimeError(f"Raw provenance mismatch: problem={problem_mismatch}, action={action_mismatch}")
    empty_problem = int(aligned["problem_normalized"].astype(str).str.strip().eq("").sum())
    empty_action = int(aligned["action_normalized"].astype(str).str.strip().eq("").sum())
    safe_mask = aligned["protected_tokens_preserved"].astype(str).str.lower().isin({"true", "1", "yes"})
    unsafe = int((~safe_mask).sum())
    if empty_problem or empty_action or unsafe:
        raise RuntimeError(f"Selective corpus QC failed: empty_problem={empty_problem}, empty_action={empty_action}, unsafe_protected={unsafe}")

    # A CSV copied between Windows tools can acquire different line endings and
    # therefore a different byte SHA while retaining identical research rows.
    # Verify every Selective representation against the frozen operational
    # index instead of failing open or accepting a filename alone.
    frozen_rows = []
    with p["frozen_index"].open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if str(row.get("representation")) != "selective_byt5":
                raise RuntimeError(f"Frozen operational index has a non-Selective row at line {line_no}.")
            frozen_rows.append((str(row.get("ident") or ""), str(row.get("normalized_text") or "")))
    expected_rows = [
        (str(row.record_id), f"{row.problem_normalized} {row.action_normalized}".strip())
        for row in aligned.itertuples(index=False)
    ]
    if frozen_rows != expected_rows:
        mismatch = next(
            (index + 1 for index, (left, right) in enumerate(zip(frozen_rows, expected_rows)) if left != right),
            min(len(frozen_rows), len(expected_rows)) + 1,
        )
        raise RuntimeError(
            "Selective corpus does not reproduce the frozen operational representation "
            f"(first mismatch at row {mismatch}; frozen={len(frozen_rows)}, source={len(expected_rows)})."
        )
    prep = json.loads(p["operational_prep_manifest"].read_text(encoding="utf-8"))
    expected_source_sha = str(prep.get("representation_source_sha256") or "").lower()
    installed_source_sha = sha256(p["source"]).lower()
    return {
        "records": len(aligned),
        "unique_ids": int(aligned["record_id"].nunique()),
        "problem_raw_mismatches": problem_mismatch,
        "action_raw_mismatches": action_mismatch,
        "empty_problem_normalized": empty_problem,
        "empty_action_normalized": empty_action,
        "protected_token_failures": unsafe,
        "frozen_operational_rows_matched": len(frozen_rows),
        "semantic_representation_match": True,
        "manifest_source_sha256": expected_source_sha,
        "installed_source_sha256": installed_source_sha,
        "source_byte_sha_matches_manifest": installed_source_sha == expected_source_sha,
        "byte_hash_note": "A byte mismatch is accepted only because all 6,169 ordered Selective representations match the frozen operational index exactly.",
        "problem_fallback_counts": {str(k): int(v) for k, v in aligned["problem_fallback"].value_counts().to_dict().items()},
        "action_fallback_counts": {str(k): int(v) for k, v in aligned["action_fallback"].value_counts().to_dict().items()},
    }


def command_preflight(args) -> None:
    p = paths()
    required = [p["root"] / "core" / "retrieval.py", p["root"] / "core" / "corpus.py", p["root"] / "core" / "normalize.py"]
    require_files(required)
    if not p["raw_freeze"].is_dir():
        raise RuntimeError(f"Existing raw RQ4/RQ5 freeze is missing: {p['raw_freeze']}")
    raw_sums = p["raw_freeze"] / "SHA256SUMS.txt"
    raw_freeze_qc = verify_checksum_manifest(p["raw_freeze"])
    source_qc = validate_source_alignment()
    identity = resolve_model_identity(require_weights=not args.static_only)
    report = {
        "version": VERSION,
        "checked_utc": utc_now(),
        "status": "ready",
        "training_performed": False,
        "representation": "selective_byt5",
        "query_features": "problem_normalized only",
        "action_used_for_retrieval_or_clustering": False,
        "source_qc": source_qc,
        "model": identity,
        "preserved_raw_freeze": str(p["raw_freeze"]),
        "preserved_raw_freeze_sums_sha256": sha256(raw_sums),
        "preserved_raw_freeze_verification": raw_freeze_qc,
    }
    if not args.no_write:
        p["run"].mkdir(parents=True, exist_ok=True)
        atomic_json(p["run"] / "PREFLIGHT.json", report)
    print(json.dumps(report, indent=2))
    print("SELECTIVE_RQ4_RQ5_PREFLIGHT_OK")


class UnionFind:
    def __init__(self, size: int):
        self.parent = list(range(size))

    def find(self, value: int) -> int:
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left: int, right: int) -> None:
        a, b = self.find(left), self.find(right)
        if a != b:
            self.parent[b] = a


def build_prepared_frames():
    import pandas as pd
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.neighbors import NearestNeighbors
    from core import normalize as normalize_module
    from core.normalize import action_family, outcome_polarity

    p = paths()
    source = load_csv(p["source"])
    raw = load_csv(p["raw"])
    source["record_id"] = source["record_id"].astype(str)
    raw["IDENT"] = raw["IDENT"].astype(str)
    source = source.set_index("record_id").loc[raw["IDENT"]].reset_index()
    cases = pd.DataFrame({
        "IDENT": source["record_id"],
        "PROBLEM": source["problem_normalized"].astype(str),
        "ACTION": source["action_normalized"].astype(str),
        "problem_raw": source["problem_raw"].astype(str),
        "action_raw": source["action_raw"].astype(str),
        "problem_normalized": source["problem_normalized"].astype(str),
        "action_normalized": source["action_normalized"].astype(str),
        "problem_fallback": source["problem_fallback"].astype(str),
        "action_fallback": source["action_fallback"].astype(str),
        "protected_tokens_preserved": source["protected_tokens_preserved"].astype(str),
    })
    cases["problem_retrieval_key"] = cases["problem_normalized"].map(canonical_problem_key)
    cases["action_family_raw"] = cases["action_raw"].map(action_family)
    cases["action_family_normalized"] = cases["action_normalized"].map(action_family)
    cases["action_family"] = cases["action_family_normalized"]
    fallback = cases["action_family"].eq("Other") & ~cases["action_family_raw"].eq("Other")
    cases.loc[fallback, "action_family"] = cases.loc[fallback, "action_family_raw"]
    cases["action_family_source"] = "normalized"
    cases.loc[fallback, "action_family_source"] = "raw_fallback"

    def detected_families(text: str) -> list[str]:
        low = str(text or "").lower()
        found = []
        for family, patterns in normalize_module._FAMILY_PATTERNS:
            if any(re.search(pattern, low) for pattern in patterns):
                found.append(family)
        return found

    raw_sets = cases["action_raw"].map(detected_families)
    normalized_sets = cases["action_normalized"].map(detected_families)
    family_order = list(normalize_module.ACTION_FAMILIES)
    cases["action_families_json"] = [
        json.dumps([family for family in family_order if family in set(raw_values) | set(normalized_values)] or ["Other"])
        for raw_values, normalized_values in zip(raw_sets, normalized_sets)
    ]
    cases["outcome_raw"] = cases["action_raw"].map(outcome_polarity)
    cases["outcome_normalized"] = cases["action_normalized"].map(outcome_polarity)

    def conservative_outcome(row) -> str:
        observed = {str(row.outcome_raw), str(row.outcome_normalized)}
        if "mixed" in observed or ("negative" in observed and "positive" in observed):
            return "mixed"
        if "negative" in observed:
            return "negative"
        if "positive" in observed:
            return "positive"
        return "unknown"

    cases["outcome"] = cases.apply(conservative_outcome, axis=1)
    cases["evidence_cluster_id"] = cases["problem_retrieval_key"].map(lambda s: stable_id("SEC-", s))

    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1, norm="l2")
    matrix = vectorizer.fit_transform(cases["problem_retrieval_key"])
    neighbours = NearestNeighbors(metric="cosine", radius=1.0 - NEAR_DUPLICATE_THRESHOLD, n_jobs=-1).fit(matrix)
    groups = neighbours.radius_neighbors(matrix, return_distance=False)
    union = UnionFind(len(cases))
    for index, row in enumerate(groups):
        for other in row:
            if int(other) > index:
                union.union(index, int(other))
    roots = [union.find(i) for i in range(len(cases))]
    root_names = {root: stable_id("SLG-", str(cases.iloc[root]["problem_retrieval_key"])) for root in set(roots)}
    cases["leakage_group_id"] = [root_names[root] for root in roots]

    group_sizes = cases.groupby("leakage_group_id").size().to_dict()
    target = {"train": 0.70 * len(cases), "dev": 0.15 * len(cases), "test": 0.15 * len(cases)}
    split_counts = Counter()
    assignment = {}
    group_ids = sorted(
        group_sizes,
        key=lambda group: (-group_sizes[group], hashlib.sha256((VERSION + "|" + group).encode("utf-8")).hexdigest()),
    )
    for group_id in group_ids:
        size = int(group_sizes[group_id])
        choices = sorted(
            target,
            key=lambda split: (
                (split_counts[split] + size - target[split]) / max(target[split], 1)
                if split_counts[split] + size > target[split]
                else -((target[split] - split_counts[split]) / max(target[split], 1)),
                split,
            ),
        )
        selected = choices[0]
        assignment[group_id] = selected
        split_counts[selected] += size
    cases["split"] = cases["leakage_group_id"].map(assignment)
    return cases


def verify_prepared_artifacts() -> dict[str, Any]:
    p = paths()
    require_files([p["cases"], p["protocol_json"], p["preregistered"], p["audit"]])
    protocol = json.loads(p["protocol_json"].read_text(encoding="utf-8"))
    audit = json.loads(p["audit"].read_text(encoding="utf-8"))
    if protocol.get("version") != VERSION or audit.get("version") != VERSION:
        raise RuntimeError("Prepared artifact version mismatch.")
    if sha256(p["cases"]) != audit.get("cases_sha256"):
        raise RuntimeError("Prepared cases SHA mismatch.")
    if sha256(p["protocol_json"]) != audit.get("protocol_sha256"):
        raise RuntimeError("Prepared protocol SHA mismatch.")
    if sha256(p["preregistered"]) != audit.get("preregistered_policy_sha256"):
        raise RuntimeError("Pre-registered selection policy SHA mismatch.")
    return audit


def command_prepare(_args) -> None:
    p = paths()
    if p["audit"].is_file():
        report = verify_prepared_artifacts()
        print(json.dumps(report, indent=2))
        print("SELECTIVE_PROTOCOL_ALREADY_PREPARED")
        return
    if p["protocol"].exists():
        raise RuntimeError(f"Incomplete protocol directory exists. Move it aside and rerun: {p['protocol']}")
    source_qc = validate_source_alignment()
    cases = build_prepared_frames()
    if len(cases) != EXPECTED_RECORDS or cases["IDENT"].nunique() != EXPECTED_RECORDS:
        raise RuntimeError("Prepared case count/identifier check failed.")
    if cases.groupby("leakage_group_id")["split"].nunique().max() != 1:
        raise RuntimeError("Leakage group crossed partitions.")
    if cases["problem_retrieval_key"].str.strip().eq("").any():
        raise RuntimeError("Empty problem retrieval key found.")

    temp = p["protocol"].with_name(p["protocol"].name + ".staging")
    if temp.exists():
        shutil.rmtree(temp)
    temp.mkdir(parents=True)
    cases_path = temp / "selective_cases_v2.csv"
    protocol_path = temp / "split_selective_v2.json"
    audit_path = temp / "SELECTIVE_DATA_AUDIT.json"
    preregistered_path = temp / "PREREGISTERED_SELECTION_POLICY.json"
    cases.to_csv(cases_path, index=False)
    payload = {
        "version": VERSION,
        "created_utc": utc_now(),
        "representation": "selective_byt5",
        "source": str(p["source"]),
        "source_sha256": sha256(p["source"]),
        "query_features": "problem_normalized plus problem-only SpERT structure",
        "action_used_for_retrieval_or_clustering": False,
        "near_duplicate_similarity_threshold": NEAR_DUPLICATE_THRESHOLD,
        "case_to_evidence_cluster": dict(zip(cases["IDENT"], cases["evidence_cluster_id"])),
        "case_to_leakage_group": dict(zip(cases["IDENT"], cases["leakage_group_id"])),
        "case_to_split": dict(zip(cases["IDENT"], cases["split"])),
        "counts": {str(k): int(v) for k, v in cases["split"].value_counts().to_dict().items()},
        "evidence_clusters": int(cases["evidence_cluster_id"].nunique()),
        "leakage_groups": int(cases["leakage_group_id"].nunique()),
    }
    atomic_json(protocol_path, payload)
    preregistered = {
        "version": VERSION,
        "created_utc": utc_now(),
        "status": "frozen_before_selective_dev",
        "representation": "selective_byt5",
        "retrieval_modes": list(PUBLIC_MODES),
        "retrieval_depth": TOP_K,
        "operational_aggregation": OPERATIONAL_AGGREGATION,
        "aggregation_ablation": "representative_only",
        "family_prior_unit": "distinct TRAIN evidence-cluster/family supports",
        "family_prior_smoothing_alpha": PRIOR_ALPHA,
        "tau_grid": list(TAU_GRID),
        "mode_selection_rule": "At tau=0 with cluster expansion: max macro action-family recall, then MRR, then Hit@1.",
        "tau_selection_rule": (
            "Eligible when Hit@1 and Hit@3 are each no more than 0.01 below tau=0 for the selected mode; "
            "among eligible values maximize macro recall, then MRR, then Hit@1, then prefer smaller tau."
        ),
        "hit_noninferiority_margin_absolute": HIT_NONINFERIORITY_MARGIN,
        "test_policy": "Select mode and tau on DEV only; open Selective TEST exactly once; no post-TEST tuning.",
        "query_features": "problem_normalized and problem-only Selective SpERT structure",
        "action_used_for_retrieval_or_clustering": False,
        "action_evidence_policy": (
            "After problem-only retrieval, reopen all TRAIN members of retrieved evidence clusters; "
            "each cluster contributes at most one vote per action family and per action pattern."
        ),
        "action_pattern": "action family + canonical component anchor + canonical fault anchor",
        "outcome_policy": "positive and unknown support corroboration; negative and mixed remain visible but never count as positive support.",
        "visibility_policy": "Single-cluster support is always shown as Limited historical evidence; weak queries show Exploratory or Nearest cases only.",
        "primary_metrics": ["Hit@1", "Hit@3", "MRR", "macro action-family recall"],
        "additional_metrics": ["pattern-set recall@3", "pattern-set recall@5", "rung distribution", "answer rate", "paired bootstrap CI"],
    }
    atomic_json(preregistered_path, preregistered)
    report = {
        "version": VERSION,
        "created_utc": utc_now(),
        "status": "complete",
        "source_qc": source_qc,
        "records": len(cases),
        "unique_ids": int(cases["IDENT"].nunique()),
        "split_counts": payload["counts"],
        "evidence_clusters": payload["evidence_clusters"],
        "leakage_groups": payload["leakage_groups"],
        "action_family_disagreements_raw_vs_normalized": int((cases["action_family_raw"] != cases["action_family_normalized"]).sum()),
        "action_family_source_counts": {str(k): int(v) for k, v in cases["action_family_source"].value_counts().to_dict().items()},
        "records_with_multiple_detected_action_families": int(cases["action_families_json"].map(lambda value: len(json.loads(value)) > 1).sum()),
        "outcome_disagreements_raw_vs_normalized": int((cases["outcome_raw"] != cases["outcome_normalized"]).sum()),
        "cases_sha256": sha256(cases_path),
        "protocol_sha256": sha256(protocol_path),
        "preregistered_policy_sha256": sha256(preregistered_path),
        "preserved_raw_freeze_sums_sha256": sha256(p["raw_freeze"] / "SHA256SUMS.txt"),
    }
    atomic_json(audit_path, report)
    p["run"].mkdir(parents=True, exist_ok=True)
    os.replace(temp, p["protocol"])
    print(json.dumps(report, indent=2))
    print("SELECTIVE_PROTOCOL_PREPARED")


def validate_prediction_file(require_complete: bool = True) -> dict[str, Any]:
    p = paths()
    require_files([p["cases"], p["predictions"]])
    expected_model = resolve_model_identity(require_weights=False)["weight_sha256"]
    expected = load_prediction_input_rows(p["cases"])
    count = entities = relations = 0
    with p["predictions"].open(encoding="utf-8") as source:
        for line_no, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Invalid prediction JSON at line {line_no}: {exc}") from exc
            if count >= len(expected):
                raise RuntimeError("Prediction file contains extra records.")
            ident, text = expected[count]
            if str(row.get("ident")) != ident or str(row.get("problem_text")) != text:
                raise RuntimeError(f"Prediction sequence/text mismatch at row {count + 1}.")
            if str(row.get("representation")) != "selective_byt5":
                raise RuntimeError(f"Prediction representation mismatch at row {count + 1}.")
            if str(row.get("model_weight_sha256") or "").lower() != str(expected_model).lower():
                raise RuntimeError(f"Prediction model identity mismatch at row {count + 1}.")
            pred = row.get("problem_pred") or {}
            entities += len(pred.get("entities") or [])
            relations += len(pred.get("relations") or [])
            count += 1
    if require_complete and count != len(expected):
        raise RuntimeError(f"Predictions incomplete: {count}/{len(expected)}")
    if require_complete and entities == 0:
        raise RuntimeError("All Selective SpERT predictions are empty; refusing results.")
    return {"records": count, "expected": len(expected), "entities": entities, "relations": relations}


def repair_truncated_jsonl_tail(path: Path) -> bool:
    """Repair only an invalid final JSONL fragment, retaining a backup copy."""
    if not path.is_file() or path.stat().st_size == 0:
        return False
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError as exc:
            if index != len(lines) - 1:
                raise RuntimeError(
                    f"Prediction JSONL is corrupt before its final line at row {index + 1}; refusing automatic repair."
                ) from exc
            backup = path.with_name(path.name + ".truncated-tail-backup.txt")
            if backup.exists():
                raise RuntimeError(f"A previous truncated-tail backup already exists: {backup}")
            atomic_text(backup, line + "\n")
            prefix = "\n".join(lines[:index])
            atomic_text(path, prefix + ("\n" if prefix else ""))
            print(f"REPAIRED TRUNCATED FINAL PREDICTION LINE; BACKUP={backup}", flush=True)
            return True
    return False


def command_precompute(args) -> None:
    p = paths()
    verify_prepared_artifacts()
    identity = resolve_model_identity(require_weights=True)
    if p["pred_manifest"].is_file():
        report = json.loads(p["pred_manifest"].read_text(encoding="utf-8"))
        qc = validate_prediction_file(require_complete=True)
        if sha256(p["predictions"]) != report.get("predictions_sha256"):
            raise RuntimeError("Completed prediction manifest SHA mismatch.")
        print(json.dumps(qc, indent=2))
        print("SELECTIVE_PROBLEM_SPERT_ALREADY_COMPLETE")
        return

    rows = load_prediction_input_rows(p["cases"])
    p["pred_dir"].mkdir(parents=True, exist_ok=True)
    completed = 0
    if p["predictions"].is_file():
        repair_truncated_jsonl_tail(p["predictions"])
        completed = validate_prediction_file(require_complete=False)["records"]
        print(f"Resuming Selective problem-only inference at {completed}/{len(rows)}", flush=True)

    service_dir = p["root"] / "services"
    sys.path.insert(0, str(service_dir))
    from spert_runtime import SpERTRunner, resolve_runtime_paths  # type: ignore

    runtime_paths = resolve_runtime_paths(
        str(p["project"]),
        spert_root=str(p["repo"] / "external" / "spert"),
        model_path=identity["model_path"],
        types_path=identity["types_path"],
    )
    force_cpu = args.cpu or os.getenv("AVIMAINT_SELECTIVE_FORCE_CPU", "").strip() == "1"
    runner = SpERTRunner(runtime_paths, rel_filter_threshold=0.4, max_span_size=10, max_pairs=1000, force_cpu=force_cpu)
    print(json.dumps({
        "role": "selective_byt5_problem_only_spert",
        "training_performed": False,
        "model_path": identity["model_path"],
        "weight_sha256": identity["weight_sha256"],
        "types_sha256": identity["types_sha256"],
        "device": runner.metadata.get("device"),
        "resume_at": completed,
    }, indent=2), flush=True)
    mode = "a" if completed else "w"
    with p["predictions"].open(mode, encoding="utf-8", newline="\n") as target:
        for index in range(completed, len(rows)):
            ident, text = rows[index]
            prediction = runner.predict(text)
            row = {
                "ident": ident,
                "problem_text": text,
                "representation": "selective_byt5",
                "model_weight_sha256": identity["weight_sha256"],
                "problem_pred": prediction,
            }
            target.write(json.dumps(row, ensure_ascii=False) + "\n")
            target.flush()
            if (index + 1) % 25 == 0 or index + 1 == len(rows):
                print(f"SELECTIVE PROBLEM SPERT {index + 1}/{len(rows)}", flush=True)
    qc = validate_prediction_file(require_complete=True)
    report = {
        "version": VERSION,
        "created_utc": utc_now(),
        "status": "complete",
        "training_performed": False,
        "inference_input": "problem_normalized only",
        "action_input_used": False,
        "representation": "selective_byt5",
        "model": identity,
        "qc": qc,
        "cases_sha256": sha256(p["cases"]),
        "predictions_sha256": sha256(p["predictions"]),
    }
    atomic_json(p["pred_manifest"], report)
    print(json.dumps(report, indent=2))
    print("SELECTIVE_PROBLEM_SPERT_COMPLETE")


def run_identity() -> dict[str, str]:
    p = paths()
    return {
        "cases_sha256": sha256(p["cases"]),
        "protocol_sha256": sha256(p["protocol_json"]),
        "preregistered_policy_sha256": sha256(p["preregistered"]),
        "predictions_sha256": sha256(p["predictions"]),
        "prediction_manifest_sha256": sha256(p["pred_manifest"]),
    }


def load_evaluation_frame():
    import pandas as pd
    from core.corpus import load_corpus

    p = paths()
    verify_prepared_artifacts()
    validate_prediction_file(require_complete=True)
    frame = load_corpus(
        p["cases"],
        predictions_path=p["predictions"],
        protocol_path=p["protocol_json"],
        require_predictions=True,
    ).df
    cases = load_csv(p["cases"]).set_index("IDENT")
    keyed = frame["ident"].astype(str)
    frame["problem_norm"] = keyed.map(cases["problem_retrieval_key"])
    frame["problem_raw"] = keyed.map(cases["problem_raw"])
    frame["action_raw"] = keyed.map(cases["action_raw"])
    frame["action_family"] = keyed.map(cases["action_family"])
    frame["action_families"] = keyed.map(cases["action_families_json"]).map(json.loads)
    frame["outcome"] = keyed.map(cases["outcome"])
    if frame[["problem_norm", "problem_raw", "action_raw", "action_family", "action_families"]].isna().any().any():
        raise RuntimeError("Prepared case mapping failed.")
    return frame


def canonical_component_v2(value: str) -> str:
    from core.normalize import canonical_component

    base = canonical_component(str(value or ""))
    aliases = {
        "intakes": "intake", "intake gaskets": "intake gasket",
        "cyls": "cylinder", "cylinders": "cylinder",
        "rocker covers": "rocker cover", "rocker cover gaskets": "rocker cover gasket",
        "magnetos": "magneto", "eng": "engine", "engines": "engine",
    }
    return aliases.get(base, base)


def _values(value) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return []


def cluster_family_priors(candidates, alpha: float = PRIOR_ALPHA) -> dict[str, float]:
    from core.normalize import ACTION_FAMILIES

    supports = set()
    for row in candidates.itertuples(index=False):
        family = str(row.action_family)
        if family == "Other" or str(row.outcome) in {"negative", "mixed"}:
            continue
        supports.add((str(row.cluster_id), family))
    counts = Counter(family for _cluster, family in supports)
    families = [family for family in ACTION_FAMILIES if counts.get(family, 0) > 0]
    total = sum(counts[family] for family in families)
    denominator = total + float(alpha) * len(families)
    if denominator <= 0:
        raise RuntimeError("TRAIN has no eligible action-family evidence.")
    return {family: (counts[family] + float(alpha)) / denominator for family in families}


def _cluster_members(candidates) -> dict[str, list[int]]:
    members: dict[str, list[int]] = {}
    for index, cluster in enumerate(candidates["cluster_id"].astype(str).tolist()):
        members.setdefault(cluster, []).append(index)
    return members


def _pattern_anchor(candidate_values, query_values, *, component: bool) -> str:
    canon = canonical_component_v2 if component else lambda value: str(value or "").strip().lower()
    candidate = [canon(value) for value in _values(candidate_values)]
    query = [canon(value) for value in _values(query_values)]
    candidate = sorted({value for value in candidate if value})
    query = sorted({value for value in query if value})
    overlap = sorted(set(candidate) & set(query))
    selected = overlap or candidate
    if not selected:
        return "(unspecified)"
    return " / ".join(selected[:3])


def aggregate_action_evidence(candidates, hits, priors, tau: float, aggregation: str, query, members=None) -> dict[str, Any]:
    members = members if members is not None else _cluster_members(candidates)
    expanded = aggregation == OPERATIONAL_AGGREGATION
    work = []
    seen_indices = set()
    for hit in hits:
        cluster = str(candidates.iloc[hit.idx].cluster_id)
        indices = members.get(cluster, [int(hit.idx)]) if expanded else [int(hit.idx)]
        for index in indices:
            if index in seen_indices:
                continue
            seen_indices.add(index)
            work.append((index, hit))

    families: dict[str, dict[str, Any]] = {}
    negative = []
    for index, hit in work:
        row = candidates.iloc[index]
        family = str(row.action_family)
        outcome = str(row.outcome)
        cluster = str(row.cluster_id)
        example = {
            "ident": str(row.ident),
            "cluster_id": cluster,
            "problem_normalized": str(row.problem),
            "problem_raw": str(getattr(row, "problem_raw", "")),
            "action_normalized": str(row.action),
            "action_raw": str(getattr(row, "action_raw", "")),
            "action_family": family,
            "outcome": outcome,
            "retrieval_score": round(float(hit.score), 8),
        }
        if outcome in {"negative", "mixed"}:
            negative.append(example)
            continue
        if family == "Other":
            continue
        bucket = families.setdefault(family, {
            "clusters": {}, "outcomes": {}, "examples": [], "patterns": {},
        })
        bucket["clusters"][cluster] = max(bucket["clusters"].get(cluster, 0.0), float(hit.score))
        bucket["outcomes"].setdefault(outcome, set()).add(cluster)
        bucket["examples"].append(example)
        component = _pattern_anchor(row.components, query.components, component=True)
        fault = _pattern_anchor(row.faults, query.faults, component=False)
        pattern_key = f"{family}|{component}|{fault}"
        pattern = bucket["patterns"].setdefault(pattern_key, {
            "family": family, "component": component, "fault": fault,
            "clusters": {}, "examples": [], "outcomes": {},
        })
        pattern["clusters"][cluster] = max(pattern["clusters"].get(cluster, 0.0), float(hit.score))
        pattern["examples"].append(example)
        pattern["outcomes"].setdefault(outcome, set()).add(cluster)

    family_rows = []
    for family, bucket in families.items():
        support = len(bucket["clusters"])
        prior = max(float(priors.get(family, 0.0)), 1e-12)
        adjusted = support / (prior ** float(tau))
        family_rows.append({
            "family": family,
            "support_clusters": support,
            "score_sum": float(sum(bucket["clusters"].values())),
            "prior": prior,
            "tau": float(tau),
            "adjusted_support": float(adjusted),
            "positive_clusters": len(bucket["outcomes"].get("positive", set())),
            "unknown_clusters": len(bucket["outcomes"].get("unknown", set())),
            "evidence_tier": "strong" if support >= 3 else ("moderate" if support == 2 else "limited"),
            "examples": sorted(bucket["examples"], key=lambda item: (-item["retrieval_score"], item["ident"]))[:5],
            "_patterns": bucket["patterns"],
        })
    # Numeric evidence criteria are descending; the final family label is an
    # ascending deterministic tie-break only.  It must not create a hidden
    # reverse-alphabetical preference when the evidence is identical.
    family_rows.sort(key=lambda item: (
        -item["adjusted_support"], -item["score_sum"],
        -item["support_clusters"], -item["positive_clusters"], item["family"],
    ))

    pattern_rows = []
    for family_rank, family in enumerate(family_rows, 1):
        patterns = []
        for key, pattern in family.pop("_patterns").items():
            patterns.append({
                "pattern_key": key,
                "family": pattern["family"],
                "component": pattern["component"],
                "fault": pattern["fault"],
                "support_clusters": len(pattern["clusters"]),
                "score_sum": float(sum(pattern["clusters"].values())),
                "positive_clusters": len(pattern["outcomes"].get("positive", set())),
                "unknown_clusters": len(pattern["outcomes"].get("unknown", set())),
                "evidence_tier": "strong" if len(pattern["clusters"]) >= 3 else ("moderate" if len(pattern["clusters"]) == 2 else "limited"),
                "examples": sorted(pattern["examples"], key=lambda item: (-item["retrieval_score"], item["ident"]))[:5],
                "family_rank": family_rank,
            })
        patterns.sort(key=lambda item: (
            -item["support_clusters"], -item["score_sum"],
            -item["positive_clusters"], item["pattern_key"],
        ))
        pattern_rows.extend(patterns)

    top_adjusted = family_rows[0]["adjusted_support"] if family_rows else 0.0
    second_adjusted = family_rows[1]["adjusted_support"] if len(family_rows) > 1 else 0.0
    support = family_rows[0]["support_clusters"] if family_rows else 0
    if support >= 3 and top_adjusted > second_adjusted:
        tier = "strong"
    elif support >= 2:
        tier = "moderate"
    elif support == 1:
        tier = "limited"
    else:
        tier = "nearest_cases_only"
    return {
        "families": family_rows,
        "patterns": pattern_rows,
        "negative_or_mixed": sorted(negative, key=lambda item: (-item["retrieval_score"], item["ident"])),
        "family_margin": float(top_adjusted - second_adjusted),
        "evidence_tier": tier,
        "expanded_case_count": len(work),
    }


def evidence_rung(candidates, hits, query) -> tuple[str, str]:
    if any(str(candidates.iloc[hit.idx].problem_norm) == str(query.problem_norm) for hit in hits):
        return "A", "Exact canonical problem match"
    if any(float((hit.channels or {}).get("char", 0.0)) >= NEAR_DUPLICATE_THRESHOLD for hit in hits):
        return "B", "Near-duplicate problem description"
    query_components = {canonical_component_v2(value) for value in _values(query.components)}
    query_faults = {str(value).strip().lower() for value in _values(query.faults)}
    for hit in hits:
        row = candidates.iloc[hit.idx]
        candidate_components = {canonical_component_v2(value) for value in _values(row.components)}
        candidate_faults = {str(value).strip().lower() for value in _values(row.faults)}
        if query_components & candidate_components and query_faults & candidate_faults:
            return "C", "Same component and fault anchors"
    return "D", "Closest text/structure matches only"


def retrieve_mode(retriever, queries, public_mode: str):
    retrieved = []
    internal_mode = PUBLIC_MODES[public_mode]
    eligible = queries[queries.action_family != "Other"]
    for query in eligible.itertuples(index=False):
        hits = retriever.search(
            query.problem_norm, query.components, query.faults, top_k=TOP_K,
            q_entity_types=query.problem_entity_types,
            q_relation_types=query.problem_relation_types,
            raw_query=query.problem, mode=internal_mode,
            exclude_groups={str(query.leakage_group_id)}, diversify=True,
        )
        retrieved.append((query, hits))
    return retrieved


def score_retrieved(candidates, retrieved, priors, tau: float, aggregation: str, *, detailed: bool = False):
    import pandas as pd

    rows = []
    members = _cluster_members(candidates)
    for query, hits in retrieved:
        evidence = aggregate_action_evidence(candidates, hits, priors, tau, aggregation, query, members=members)
        ranked = [item["family"] for item in evidence["families"]]
        patterns = evidence["patterns"]
        truth = str(query.action_family)
        truth_set = [family for family in _values(getattr(query, "action_families", [])) if family != "Other"] or [truth]
        rank = ranked.index(truth) + 1 if truth in ranked else 0
        pattern_rank = next((index for index, item in enumerate(patterns, 1) if item["family"] == truth), 0)
        family_set_recall_3 = len(set(truth_set) & set(ranked[:3])) / len(set(truth_set))
        family_set_recall_5 = len(set(truth_set) & set(ranked[:5])) / len(set(truth_set))
        predicted = ranked[0] if ranked else ""
        top = float(hits[0].score) if hits else 0.0
        second = float(hits[1].score) if len(hits) > 1 else 0.0
        rung, rung_label = evidence_rung(candidates, hits, query)
        tier = evidence["evidence_tier"]
        if tier == "nearest_cases_only" and rung == "C":
            tier = "exploratory"
        row = {
            "ident": str(query.ident),
            "leakage_group_id": str(query.leakage_group_id),
            "true_family": truth,
            "predicted_family": predicted,
            "rank": rank,
            "pattern_rank": pattern_rank,
            "top1_correct": predicted == truth,
            "top3_correct": 0 < rank <= 3,
            "top5_correct": 0 < rank <= 5,
            "pattern_recall_at_3": 0 < pattern_rank <= 3,
            "pattern_recall_at_5": 0 < pattern_rank <= 5,
            "recorded_family_set_recall_at_3": family_set_recall_3,
            "recorded_family_set_recall_at_5": family_set_recall_5,
            "rr": 1.0 / rank if rank else 0.0,
            "ndcg5": 1.0 / math.log2(rank + 1) if 0 < rank <= 5 else 0.0,
            "top_score": top,
            "margin": top - second,
            "family_margin": evidence["family_margin"],
            "support_clusters": evidence["families"][0]["support_clusters"] if evidence["families"] else 0,
            "answer_available": bool(ranked),
            "evidence_rung": rung,
            "evidence_rung_label": rung_label,
            "evidence_tier": tier,
            "ranked_family_count": len(ranked),
            "ranked_pattern_count": len(patterns),
            "negative_or_mixed_count": len(evidence["negative_or_mixed"]),
            "single_support_alternative_visible": any(item["support_clusters"] == 1 for item in evidence["families"]),
            "tau": float(tau),
            "aggregation": aggregation,
        }
        if detailed:
            row.update({
                "query_problem_normalized": str(query.problem),
                "query_problem_raw": str(getattr(query, "problem_raw", "")),
                "query_components_json": json.dumps(_values(query.components), ensure_ascii=False),
                "query_faults_json": json.dumps(_values(query.faults), ensure_ascii=False),
                "recorded_action_families_json": json.dumps(truth_set, ensure_ascii=False),
                "ranked_families_json": json.dumps(evidence["families"], ensure_ascii=False),
                "ranked_patterns_json": json.dumps(patterns, ensure_ascii=False),
                "negative_or_mixed_evidence_json": json.dumps(evidence["negative_or_mixed"][:20], ensure_ascii=False),
                "nearest_candidate_ids_json": json.dumps([str(candidates.iloc[hit.idx].ident) for hit in hits[:10]]),
                "expanded_case_count": evidence["expanded_case_count"],
            })
        rows.append(row)
    predictions = pd.DataFrame(rows)
    if predictions.empty:
        raise RuntimeError("No eligible evaluation queries were produced.")
    per_family = predictions.groupby("true_family").agg(queries=("ident", "size"), hit_at_1=("top1_correct", "mean"))
    rung_counts = predictions["evidence_rung"].value_counts().sort_index()
    tier_counts = predictions["evidence_tier"].value_counts().sort_index()
    metrics = {
        "queries": len(predictions),
        "hit_at_1": float(predictions.top1_correct.mean()),
        "hit_at_3": float(predictions.top3_correct.mean()),
        "hit_at_5": float(predictions.top5_correct.mean()),
        "mrr": float(predictions.rr.mean()),
        "ndcg_at_5": float(predictions.ndcg5.mean()),
        "macro_action_family_recall": float(per_family.hit_at_1.mean()),
        "pattern_set_recall_at_3": float(predictions.pattern_recall_at_3.mean()),
        "pattern_set_recall_at_5": float(predictions.pattern_recall_at_5.mean()),
        "recorded_multi_family_set_recall_at_3": float(predictions.recorded_family_set_recall_at_3.mean()),
        "recorded_multi_family_set_recall_at_5": float(predictions.recorded_family_set_recall_at_5.mean()),
        "answer_rate": float(predictions.answer_available.mean()),
        "single_support_result_rate": float((predictions.support_clusters == 1).mean()),
        "queries_with_single_support_alternative_rate": float(predictions.single_support_alternative_visible.mean()),
        "rung_distribution": {str(key): int(value) for key, value in rung_counts.items()},
        "evidence_tier_distribution": {str(key): int(value) for key, value in tier_counts.items()},
        "per_family": {
            str(index): {"queries": int(row.queries), "hit_at_1": float(row.hit_at_1)}
            for index, row in per_family.iterrows()
        },
        "tau": float(tau),
        "aggregation": aggregation,
        "interpretation": "Agreement with the recorded historical action family, not technical correctness.",
    }
    return metrics, predictions


def bootstrap_intervals(predictions, repetitions: int = 2000, seed: int = 20260907) -> dict[str, Any]:
    import numpy as np

    rng = np.random.default_rng(seed)
    hit_values = predictions.top1_correct.astype(float).to_numpy()
    family_arrays = [group.top1_correct.astype(float).to_numpy() for _family, group in predictions.groupby("true_family")]
    hit_samples, macro_samples = [], []
    for _ in range(repetitions):
        hit_samples.append(float(rng.choice(hit_values, size=len(hit_values), replace=True).mean()))
        macro_samples.append(float(np.mean([
            rng.choice(values, size=len(values), replace=True).mean() for values in family_arrays
        ])))
    return {
        "method": "query bootstrap for Hit@1; stratified family bootstrap for macro recall",
        "repetitions": repetitions,
        "seed": seed,
        "hit_at_1_95ci": [float(x) for x in np.quantile(hit_samples, [0.025, 0.975])],
        "macro_recall_95ci": [float(x) for x in np.quantile(macro_samples, [0.025, 0.975])],
    }


def paired_comparison(selected, baseline, repetitions: int = 2000, seed: int = 20260908) -> dict[str, Any]:
    import numpy as np

    merged = selected[["ident", "true_family", "top1_correct"]].merge(
        baseline[["ident", "top1_correct"]], on="ident", suffixes=("_selected", "_tau0"), validate="one_to_one"
    )
    a = merged.top1_correct_selected.astype(int).to_numpy()
    b = merged.top1_correct_tau0.astype(int).to_numpy()
    selected_only = int(((a == 1) & (b == 0)).sum())
    tau0_only = int(((a == 0) & (b == 1)).sum())
    discordant = selected_only + tau0_only
    if discordant:
        tail = sum(math.comb(discordant, k) for k in range(0, min(selected_only, tau0_only) + 1)) / (2 ** discordant)
        p_value = min(1.0, 2.0 * tail)
    else:
        p_value = 1.0
    rng = np.random.default_rng(seed)
    differences = []
    indices = np.arange(len(merged))
    for _ in range(repetitions):
        sampled = rng.choice(indices, size=len(indices), replace=True)
        differences.append(float(a[sampled].mean() - b[sampled].mean()))
    return {
        "selected_minus_tau0_hit_at_1": float(a.mean() - b.mean()),
        "paired_bootstrap_95ci": [float(x) for x in np.quantile(differences, [0.025, 0.975])],
        "mcnemar_exact_two_sided_p": float(p_value),
        "selected_only_correct": selected_only,
        "tau0_only_correct": tau0_only,
    }


def command_evaluate(args) -> None:
    import pandas as pd
    from core.retrieval import Retriever

    p = paths()
    identity = run_identity()
    output = p[args.partition]
    marker = output / ("RQ4_DEV_SELECTION.json" if args.partition == "dev" else "RQ4_FINAL_TEST.json")
    if marker.is_file():
        existing = json.loads(marker.read_text(encoding="utf-8"))
        if existing.get("run_identity") != identity:
            raise RuntimeError(f"Existing {args.partition} results belong to different inputs.")
        if args.partition == "test":
            require_files([p["test_lock"]])
            existing_lock = json.loads(p["test_lock"].read_text(encoding="utf-8"))
            if (
                existing_lock.get("locked")
                and existing_lock.get("status") == "opened"
                and existing_lock.get("run_identity") == identity
                and existing.get("selected_mode") == existing_lock.get("selected_mode")
                and float(existing.get("selected_tau")) == float(existing_lock.get("selected_tau"))
            ):
                # Recover the tiny crash window after the atomic result rename
                # but before finalising the lock; no scoring is repeated.
                existing_lock.update({
                    "status": "complete",
                    "completed_utc": utc_now(),
                    "final_test_sha256": sha256(marker),
                })
                atomic_json(p["test_lock"], existing_lock)
            if (
                not existing_lock.get("locked")
                or existing_lock.get("status") != "complete"
                or existing_lock.get("run_identity") != identity
                or existing_lock.get("final_test_sha256") != sha256(marker)
            ):
                raise RuntimeError("Existing Selective TEST result does not match its completed lock.")
        print(json.dumps(existing, indent=2))
        print(f"SELECTIVE_RQ4_{args.partition.upper()}_ALREADY_COMPLETE")
        return
    if output.exists():
        raise RuntimeError(f"Incomplete {args.partition} directory exists. Move it aside and rerun: {output}")
    dev_selection = None
    if args.partition == "test":
        if not args.confirm_final_test:
            raise RuntimeError("Selective TEST is gated; pass --confirm-final-test after reviewing DEV selection.")
        require_files([p["dev"] / "RQ4_DEV_SELECTION.json"])
        dev_selection = json.loads((p["dev"] / "RQ4_DEV_SELECTION.json").read_text(encoding="utf-8"))
        if dev_selection.get("run_identity") != identity:
            raise RuntimeError("DEV selection input identity changed before TEST.")
        expected_lock = {
            "version": VERSION,
            "locked": True,
            "status": "opened",
            "no_post_test_tuning": True,
            "selected_mode": str(dev_selection["selected_mode"]),
            "selected_tau": float(dev_selection["selected_tau"]),
            "selected_aggregation": OPERATIONAL_AGGREGATION,
            "run_identity": identity,
        }
        if p["test_lock"].is_file():
            existing_lock = json.loads(p["test_lock"].read_text(encoding="utf-8"))
            comparable = {key: existing_lock.get(key) for key in expected_lock if key != "status"}
            expected_comparable = {key: value for key, value in expected_lock.items() if key != "status"}
            if comparable != expected_comparable or existing_lock.get("status") != "opened":
                raise RuntimeError("Selective final TEST lock exists with a different or completed identity.")
            print("RESUMING THE ALREADY-OPENED, LOCKED SELECTIVE TEST COMPUTATION", flush=True)
        else:
            expected_lock["opened_utc"] = utc_now()
            atomic_json(p["test_lock"], expected_lock)
            print("SELECTIVE TEST OPENED AND PERMANENTLY LOCKED BEFORE SCORING", flush=True)

    frame = load_evaluation_frame()
    train = frame[frame.frozen_split == "train"].reset_index(drop=True)
    queries = frame[frame.frozen_split == args.partition].reset_index(drop=True)
    if train.empty or queries.empty:
        raise RuntimeError(f"Empty TRAIN or {args.partition.upper()} partition.")
    priors = cluster_family_priors(train)
    retriever = Retriever(train)
    stage = output.with_name(output.name + ".staging")
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    atomic_json(stage / "family_priors_train_cluster_unit.json", {
        "unit": "distinct TRAIN evidence-cluster/family supports",
        "alpha": PRIOR_ALPHA,
        "priors": priors,
    })

    if args.partition == "dev":
        grid_rows = []
        metrics_by_config = {}
        # Stage 1: choose the retrieval mode under the operational
        # cluster-expanded aggregation with the uncorrected tau=0 vote.
        for public_mode in PUBLIC_MODES:
            retrieved = retrieve_mode(retriever, queries, public_mode)
            metrics, _predictions = score_retrieved(train, retrieved, priors, 0.0, OPERATIONAL_AGGREGATION)
            key = f"{public_mode}|{OPERATIONAL_AGGREGATION}|tau=0.00|mode_selection"
            metrics_by_config[key] = metrics
            grid_rows.append({"stage": "mode_selection", "mode": public_mode, **metrics})
            print(key, json.dumps({name: metrics[name] for name in ("hit_at_1", "hit_at_3", "mrr", "macro_action_family_recall")}), flush=True)
        grid = pd.DataFrame(grid_rows)
        mode_row = grid.sort_values(
            ["macro_action_family_recall", "mrr", "hit_at_1", "mode"],
            ascending=[False, False, False, True],
        ).iloc[0]
        selected_mode = str(mode_row["mode"])

        # Stage 2: tune only tau for the already-selected retrieval mode. This
        # avoids a joint mode/tau search and keeps the methodological roles
        # separate and reproducible.
        selected_retrieved = retrieve_mode(retriever, queries, selected_mode)
        tau_metrics_rows = []
        for tau in TAU_GRID:
            metrics, _predictions = score_retrieved(
                train, selected_retrieved, priors, tau, OPERATIONAL_AGGREGATION
            )
            key = f"{selected_mode}|{OPERATIONAL_AGGREGATION}|tau={tau:.2f}|tau_selection"
            metrics_by_config[key] = metrics
            tau_metrics_rows.append({"stage": "tau_selection", "mode": selected_mode, **metrics})
            print(key, json.dumps({name: metrics[name] for name in ("hit_at_1", "hit_at_3", "mrr", "macro_action_family_recall")}), flush=True)
        tau_rows = pd.DataFrame(tau_metrics_rows)
        baseline = tau_rows[tau_rows.tau == 0.0].iloc[0]
        tau_rows["eligible_hit_noninferiority"] = (
            (tau_rows.hit_at_1 >= float(baseline.hit_at_1) - HIT_NONINFERIORITY_MARGIN)
            & (tau_rows.hit_at_3 >= float(baseline.hit_at_3) - HIT_NONINFERIORITY_MARGIN)
        )
        eligible = tau_rows[tau_rows.eligible_hit_noninferiority]
        selected_row = eligible.sort_values(
            ["macro_action_family_recall", "mrr", "hit_at_1", "tau"],
            ascending=[False, False, False, True],
        ).iloc[0]
        selected_tau = float(selected_row.tau)
        selected_metrics, selected_predictions = score_retrieved(
            train, selected_retrieved, priors, selected_tau, OPERATIONAL_AGGREGATION, detailed=True
        )
        tau0_metrics, tau0_predictions = score_retrieved(
            train, selected_retrieved, priors, 0.0, OPERATIONAL_AGGREGATION, detailed=True
        )
        representative_metrics, representative_predictions = score_retrieved(
            train, selected_retrieved, priors, selected_tau, "representative_only", detailed=True
        )
        metrics_by_config[f"{selected_mode}|representative_only|tau={selected_tau:.2f}|ablation"] = representative_metrics
        pd.concat([grid, tau_rows], ignore_index=True).to_csv(stage / "DEV_CONFIGURATION_GRID.csv", index=False)
        tau_rows.to_csv(stage / "DEV_TAU_SELECTION.csv", index=False)
        selected_predictions.to_csv(stage / "predictions_selected.csv", index=False)
        selected_predictions.to_csv(stage / f"predictions_{selected_mode}.csv", index=False)
        tau0_predictions.to_csv(stage / "predictions_tau0_cluster_expanded.csv", index=False)
        representative_predictions.to_csv(stage / "predictions_representative_ablation.csv", index=False)
        atomic_json(stage / "metrics_all.json", metrics_by_config)
        result = {
            "version": VERSION,
            "created_utc": utc_now(),
            "representation": "selective_byt5",
            "selected_mode": selected_mode,
            "internal_mode": PUBLIC_MODES[selected_mode],
            "selected_tau": selected_tau,
            "selected_aggregation": OPERATIONAL_AGGREGATION,
            "mode_selection_rule": "tau=0 cluster-expanded: max macro recall, then MRR, then Hit@1",
            "tau_selection_rule": "Hit@1 and Hit@3 within 0.01 of tau=0; then max macro recall, MRR, Hit@1, smaller tau",
            "run_identity": identity,
            "selected_metrics": selected_metrics,
            "tau0_metrics": tau0_metrics,
            "representative_ablation_metrics": representative_metrics,
            "selected_bootstrap_intervals": bootstrap_intervals(selected_predictions),
            "selected_vs_tau0": paired_comparison(selected_predictions, tau0_predictions),
            "family_priors": priors,
            "test_not_opened": True,
        }
        atomic_json(stage / "RQ4_DEV_SELECTION.json", result)
    else:
        selected_mode = str(dev_selection["selected_mode"])
        selected_tau = float(dev_selection["selected_tau"])
        selected_retrieved = None
        frozen_mode_metrics = {}
        for public_mode in PUBLIC_MODES:
            retrieved = retrieve_mode(retriever, queries, public_mode)
            metrics, _ = score_retrieved(train, retrieved, priors, selected_tau, OPERATIONAL_AGGREGATION)
            frozen_mode_metrics[public_mode] = metrics
            if public_mode == selected_mode:
                selected_retrieved = retrieved
        if selected_retrieved is None:
            raise RuntimeError("DEV-selected retrieval mode is unavailable.")
        selected_metrics, selected_predictions = score_retrieved(
            train, selected_retrieved, priors, selected_tau, OPERATIONAL_AGGREGATION, detailed=True
        )
        tau0_metrics, tau0_predictions = score_retrieved(
            train, selected_retrieved, priors, 0.0, OPERATIONAL_AGGREGATION, detailed=True
        )
        representative_metrics, representative_predictions = score_retrieved(
            train, selected_retrieved, priors, selected_tau, "representative_only", detailed=True
        )
        selected_predictions.to_csv(stage / "predictions_selected.csv", index=False)
        selected_predictions.to_csv(stage / f"predictions_{selected_mode}.csv", index=False)
        tau0_predictions.to_csv(stage / "predictions_tau0_cluster_expanded.csv", index=False)
        representative_predictions.to_csv(stage / "predictions_representative_ablation.csv", index=False)
        atomic_json(stage / "metrics_all.json", frozen_mode_metrics)
        result = {
            "version": VERSION,
            "created_utc": utc_now(),
            "representation": "selective_byt5",
            "selected_mode": selected_mode,
            "internal_mode": PUBLIC_MODES[selected_mode],
            "selected_tau": selected_tau,
            "selected_aggregation": OPERATIONAL_AGGREGATION,
            "run_identity": identity,
            "selected_configuration_metrics": selected_metrics,
            "tau0_comparator_metrics": tau0_metrics,
            "representative_ablation_metrics": representative_metrics,
            "selected_bootstrap_intervals": bootstrap_intervals(selected_predictions),
            "selected_vs_tau0": paired_comparison(selected_predictions, tau0_predictions),
            "all_mode_frozen_comparisons_at_selected_tau": frozen_mode_metrics,
            "no_post_test_tuning": True,
            "interpretation": "Historical action-family agreement only; not technical correctness or approval.",
        }
        atomic_json(stage / "RQ4_FINAL_TEST.json", result)
    os.replace(stage, output)
    if args.partition == "test":
        completed_lock = json.loads(p["test_lock"].read_text(encoding="utf-8"))
        completed_lock.update({
            "status": "complete",
            "completed_utc": utc_now(),
            "final_test_sha256": sha256(output / "RQ4_FINAL_TEST.json"),
        })
        atomic_json(p["test_lock"], completed_lock)
    print(json.dumps(result, indent=2))
    print(f"SELECTIVE_RQ4_{args.partition.upper()}_COMPLETE")


def command_rq5(_args) -> None:
    import joblib
    import numpy as np
    import pandas as pd
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import brier_score_loss
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    p = paths()
    require_files([p["test_lock"], p["dev"] / "RQ4_DEV_SELECTION.json", p["test"] / "RQ4_FINAL_TEST.json"])
    if p["rq5"].exists():
        result_path = p["rq5"] / "RQ5_PLANNING_SUPPORT.json"
        if not result_path.is_file():
            raise RuntimeError(f"Incomplete RQ5 directory exists: {p['rq5']}")
        print(result_path.read_text(encoding="utf-8"))
        print("SELECTIVE_RQ5_ALREADY_COMPLETE")
        return
    selection = json.loads((p["dev"] / "RQ4_DEV_SELECTION.json").read_text(encoding="utf-8"))
    lock = json.loads(p["test_lock"].read_text(encoding="utf-8"))
    if (
        not lock.get("locked")
        or lock.get("status") != "complete"
        or selection.get("selected_mode") != lock.get("selected_mode")
        or float(selection.get("selected_tau")) != float(lock.get("selected_tau"))
    ):
        raise RuntimeError("DEV selection and TEST lock disagree.")
    if selection.get("run_identity") != run_identity() or lock.get("run_identity") != run_identity():
        raise RuntimeError("RQ4 input identity changed before RQ5 calibration.")
    mode = selection["selected_mode"]
    selected_tau = float(selection["selected_tau"])
    dev = pd.read_csv(p["dev"] / "predictions_selected.csv")
    test = pd.read_csv(p["test"] / "predictions_selected.csv")
    columns = ["top_score", "margin", "support_clusters"]
    xd = dev[columns].astype(float).to_numpy()
    yd = dev.top1_correct.astype(int).to_numpy()
    xt = test[columns].astype(float).to_numpy()
    yt = test.top1_correct.astype(int).to_numpy()
    if len(np.unique(yd)) < 2:
        raise RuntimeError("DEV correctness has one class; calibration is not identifiable.")
    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, random_state=42)).fit(xd, yd)
    probability = model.predict_proba(xt)[:, 1]
    test["historical_agreement_probability"] = probability

    def ece(y, pred, bins=10):
        value = 0.0
        edges = np.linspace(0, 1, bins + 1)
        for low, high in zip(edges[:-1], edges[1:]):
            mask = (pred >= low) & (pred < (high if high < 1 else high + 1e-12))
            if mask.any():
                value += mask.mean() * abs(y[mask].mean() - pred[mask].mean())
        return float(value)

    risk = []
    order = np.argsort(-probability)
    ordered = yt[order]
    for coverage in np.linspace(0.1, 1.0, 10):
        size = max(1, int(np.ceil(len(ordered) * coverage)))
        accuracy = float(ordered[:size].mean())
        risk.append({"coverage": float(coverage), "agreement_accuracy": accuracy, "risk": 1.0 - accuracy})
    reliability = []
    edges = np.linspace(0, 1, 11)
    for low, high in zip(edges[:-1], edges[1:]):
        mask = (probability >= low) & (probability < (high if high < 1 else high + 1e-12))
        reliability.append({
            "lower": float(low), "upper": float(high), "count": int(mask.sum()),
            "mean_probability": float(probability[mask].mean()) if mask.any() else None,
            "agreement_rate": float(yt[mask].mean()) if mask.any() else None,
        })
    threshold_summary = []
    for threshold in (0.50, 0.60, 0.70, 0.80, 0.90):
        mask = probability >= threshold
        threshold_summary.append({
            "threshold": threshold,
            "answer_rate_if_applied": float(mask.mean()),
            "agreement_rate_among_answered": float(yt[mask].mean()) if mask.any() else None,
            "display_policy": "reporting only; the evidence-first dashboard does not hide lower-probability results",
        })
    rung_summary = []
    for rung, group in test.groupby("evidence_rung"):
        rung_summary.append({
            "rung": str(rung), "queries": int(len(group)),
            "share": float(len(group) / len(test)),
            "agreement_rate": float(group.top1_correct.astype(int).mean()),
            "mean_probability": float(group.historical_agreement_probability.mean()),
        })

    stage = p["rq5"].with_name(p["rq5"].name + ".staging")
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    test.to_csv(stage / "calibrated_test_predictions.csv", index=False)
    model_path = stage / "rq5_agreement_calibrator.joblib"
    joblib.dump(model, model_path)
    scaler = model.named_steps.get("standardscaler")
    logistic = model.named_steps.get("logisticregression")
    result = {
        "version": VERSION,
        "created_utc": utc_now(),
        "representation": "selective_byt5",
        "selected_retrieval_mode": mode,
        "selected_tau": selected_tau,
        "selected_aggregation": OPERATIONAL_AGGREGATION,
        "calibration_population": "DEV only",
        "evaluation_population": "locked TEST",
        "run_identity": run_identity(),
        "ece_10_bins": ece(yt, probability),
        "brier_score": float(brier_score_loss(yt, probability)),
        "risk_coverage": risk,
        "threshold_reporting": threshold_summary,
        "reliability_bins": reliability,
        "rung_distribution_and_agreement": rung_summary,
        "model_artifact": "rq5_agreement_calibrator.joblib",
        "model_artifact_sha256": sha256(model_path),
        "features": columns,
        "scaler_mean": [float(value) for value in scaler.mean_],
        "scaler_scale": [float(value) for value in scaler.scale_],
        "logistic_coefficients": [float(value) for value in logistic.coef_[0]],
        "logistic_intercept": float(logistic.intercept_[0]),
        "visibility_policy": "Calibration grades historical agreement; it never suppresses Limited, Exploratory, or Nearest-only evidence.",
        "interpretation": "Probability estimates historical action-family agreement only. It is NOT probability of technical correctness, safety, or regulatory applicability.",
    }
    atomic_json(stage / "RQ5_PLANNING_SUPPORT.json", result)
    os.replace(stage, p["rq5"])
    print(json.dumps(result, indent=2))
    print("SELECTIVE_RQ5_COMPLETE")


def manual_paths() -> dict[str, Path]:
    base = paths()["manual"]
    return {
        "base": base,
        "a": base / "PHASE_A_problem_relevance_BLINDED.csv",
        "private": base / "PRIVATE_DO_NOT_OPEN_UNTIL_PHASE_A_COMPLETE.jsonl",
        "b": base / "PHASE_B_action_applicability_BLINDED.csv",
        "manifest": base / "MANUAL_REVIEW_MANIFEST.json",
        "results": base / "MANUAL_REVIEW_RESULTS.json",
        "scored": base / "manual_review_scored_pairs.csv",
        "per_query": base / "manual_review_per_query.csv",
    }


def old_review_labels() -> dict[tuple[str, str], dict[str, str]]:
    p = paths()
    old = p["raw_freeze"] / "rq4_case_retrieval" / "manual_review" / "manual_review_scored_pairs.csv"
    if not old.is_file():
        return {}
    frame = load_csv(old)
    required = {"query_id", "candidate_id", "problem_relevance_0_1_2", "action_applicability_0_1_2"}
    if not required.issubset(frame.columns):
        return {}
    return {
        (str(row.query_id), str(row.candidate_id)): {
            "problem": str(row.problem_relevance_0_1_2),
            "action": str(row.action_applicability_0_1_2),
        }
        for row in frame.itertuples(index=False)
    }


def proportional_sample(frame, count: int, seed: int):
    import numpy as np
    import pandas as pd
    if len(frame) <= count:
        return frame.copy()
    counts = frame["action_family"].value_counts().sort_index()
    exact = counts / counts.sum() * count
    quotas = np.floor(exact).astype(int)
    remaining = count - int(quotas.sum())
    for family in (exact - quotas).sort_values(ascending=False).index[:remaining]:
        quotas.loc[family] += 1
    parts = []
    for index, (family, quota) in enumerate(quotas.items()):
        if quota:
            subset = frame[frame.action_family == family]
            parts.append(subset.sample(n=min(int(quota), len(subset)), random_state=seed + index))
    sampled = pd.concat(parts)
    if len(sampled) < count:
        remainder = frame.drop(sampled.index)
        sampled = pd.concat([sampled, remainder.sample(n=count - len(sampled), random_state=seed + 10000)])
    return sampled.sample(frac=1.0, random_state=seed + 20000).head(count)


def selected_configuration() -> tuple[str, str, float, str]:
    p = paths()
    selection = json.loads((p["dev"] / "RQ4_DEV_SELECTION.json").read_text(encoding="utf-8"))
    lock = json.loads(p["test_lock"].read_text(encoding="utf-8"))
    if (
        not lock.get("locked")
        or lock.get("status") != "complete"
        or selection["selected_mode"] != lock["selected_mode"]
        or float(selection["selected_tau"]) != float(lock["selected_tau"])
    ):
        raise RuntimeError("RQ4 DEV selection and TEST lock must exist and agree.")
    return (
        str(selection["selected_mode"]),
        str(selection["internal_mode"]),
        float(selection["selected_tau"]),
        str(selection["selected_aggregation"]),
    )


def build_manual_pool(query_count=100, top_k=5, seed=20260901) -> None:
    import pandas as pd
    from core.retrieval import Retriever

    p, m = paths(), manual_paths()
    public_mode, internal_mode, selected_tau, selected_aggregation = selected_configuration()
    frame = load_evaluation_frame()
    train = frame[frame.frozen_split == "train"].reset_index(drop=True)
    test = frame[(frame.frozen_split == "test") & (frame.action_family != "Other")].copy()
    sample = proportional_sample(test, min(query_count, len(test)), seed)
    retriever = Retriever(train)
    old = old_review_labels()
    visible, private = [], []
    for query in sample.itertuples(index=False):
        hits = retriever.search(
            query.problem_norm, query.components, query.faults, top_k=top_k,
            q_entity_types=query.problem_entity_types, q_relation_types=query.problem_relation_types,
            raw_query=query.problem, mode=internal_mode,
            exclude_groups={str(query.leakage_group_id)}, diversify=True,
        )
        for rank, hit in enumerate(hits, 1):
            candidate = train.iloc[hit.idx]
            key = (str(query.ident), str(candidate.ident))
            carried = old.get(key)
            pair_id = stable_id("SMR-", f"{query.ident}|{candidate.ident}|{public_mode}|{selected_tau}|{rank}|{VERSION}")
            visible.append({
                "pair_id": pair_id,
                "query_id": str(query.ident),
                "query_problem_normalized": str(query.problem),
                "query_problem_raw": str(query.problem_raw),
                "candidate_problem_normalized": str(candidate.problem),
                "candidate_problem_raw": str(candidate.problem_raw),
                "problem_relevance_0_1_2": carried["problem"] if carried else "",
                "phase_a_label_source": "carried_forward_raw_v1" if carried else "new_review_required",
                "phase_a_notes": "",
            })
            private.append({
                "pair_id": pair_id,
                "query_id": str(query.ident),
                "candidate_id": str(candidate.ident),
                "rank": rank,
                "selected_mode": public_mode,
                "selected_tau": selected_tau,
                "selected_aggregation": selected_aggregation,
                "query_true_historical_action_family": str(query.action_family),
                "candidate_historical_action_normalized": str(candidate.action),
                "candidate_historical_action_raw": str(candidate.action_raw),
                "candidate_historical_action_family": str(candidate.action_family),
                "candidate_cluster_id": str(candidate.cluster_id),
                "candidate_leakage_group_id": str(candidate.leakage_group_id),
                "retrieval_score": float(hit.score),
                "carried_action_label": carried["action"] if carried else "",
            })
    m["base"].mkdir(parents=True, exist_ok=True)
    phase_a = pd.DataFrame(visible).sample(frac=1.0, random_state=seed + 30000).reset_index(drop=True)
    phase_a.to_csv(m["a"], index=False)
    with m["private"].open("w", encoding="utf-8", newline="\n") as target:
        for row in private:
            target.write(json.dumps(row, ensure_ascii=False) + "\n")
    carried_count = int((phase_a.phase_a_label_source == "carried_forward_raw_v1").sum())
    manifest = {
        "version": VERSION,
        "created_utc": utc_now(),
        "status": "phase_a_ready",
        "selected_retrieval_mode": public_mode,
        "selected_tau": selected_tau,
        "selected_aggregation": selected_aggregation,
        "source_partition": "locked selective TEST",
        "query_count": int(sample.ident.nunique()),
        "candidate_depth": top_k,
        "visible_pair_count": len(phase_a),
        "phase_a_carried_forward_pairs": carried_count,
        "phase_a_new_pairs_requiring_review": len(phase_a) - carried_count,
        "carry_forward_rule": "Only identical query_id + candidate_id pairs from the frozen raw-v1 blinded review are reused.",
        "phase_a_sha256_at_creation": sha256(m["a"]),
        "private_sha256": sha256(m["private"]),
        "interpretation": "Manual judgments evaluate historical evidence relevance, not technical correctness or approval.",
    }
    atomic_json(m["manifest"], manifest)
    print(json.dumps(manifest, indent=2))
    print(f"Fill blank problem_relevance_0_1_2 cells in: {m['a']}")
    print("SELECTIVE_MANUAL_PHASE_A_READY")


def parse_rating(series, name: str):
    import pandas as pd
    values = pd.to_numeric(series, errors="coerce")
    bad = values.isna() | ~values.isin([0, 1, 2])
    if bad.any():
        raise RuntimeError(f"{name} is incomplete/invalid for {int(bad.sum())} rows. Use only 0, 1, or 2.")
    return values.astype(int)


def read_private():
    import pandas as pd
    m = manual_paths()
    rows = [json.loads(line) for line in m["private"].read_text(encoding="utf-8").splitlines() if line.strip()]
    return pd.DataFrame(rows)


def reveal_manual_phase_b() -> None:
    import pandas as pd
    m = manual_paths()
    phase_a = load_csv(m["a"])
    phase_a["problem_relevance_0_1_2"] = parse_rating(phase_a["problem_relevance_0_1_2"], "problem_relevance_0_1_2")
    private = read_private()
    merged = phase_a.merge(private, on=["pair_id", "query_id"], how="left", validate="one_to_one")
    relevant = merged[merged.problem_relevance_0_1_2 >= 1].copy()
    phase_b = relevant[[
        "pair_id", "query_id", "query_problem_normalized", "query_problem_raw",
        "candidate_problem_normalized", "candidate_problem_raw", "problem_relevance_0_1_2",
        "candidate_historical_action_normalized", "candidate_historical_action_raw",
        "candidate_historical_action_family", "carried_action_label",
    ]].copy()
    phase_b["action_applicability_0_1_2"] = phase_b["carried_action_label"]
    phase_b["phase_b_label_source"] = phase_b["carried_action_label"].map(lambda value: "carried_forward_raw_v1" if str(value).strip() else "new_review_required")
    phase_b["phase_b_notes"] = ""
    phase_b = phase_b.drop(columns=["carried_action_label"]).sample(frac=1.0, random_state=424242).reset_index(drop=True)
    phase_b.to_csv(m["b"], index=False)
    manifest = json.loads(m["manifest"].read_text(encoding="utf-8"))
    carried = int((phase_b.phase_b_label_source == "carried_forward_raw_v1").sum())
    manifest.update({
        "status": "phase_b_ready",
        "phase_a_completed_sha256": sha256(m["a"]),
        "phase_b_rows": len(phase_b),
        "phase_b_carried_forward_pairs": carried,
        "phase_b_new_pairs_requiring_review": len(phase_b) - carried,
        "phase_b_sha256_at_creation": sha256(m["b"]),
    })
    atomic_json(m["manifest"], manifest)
    print(json.dumps(manifest, indent=2))
    print(f"Fill blank action_applicability_0_1_2 cells in: {m['b']}")
    print("SELECTIVE_MANUAL_PHASE_B_READY")


def ndcg(group, k=5) -> float:
    import numpy as np
    ordered = group.sort_values("rank").head(k)
    gains = ordered.problem_relevance_0_1_2.astype(float).to_numpy()
    dcg = sum((2.0**gain - 1.0) / math.log2(index + 2) for index, gain in enumerate(gains))
    ideal = np.sort(gains)[::-1]
    idcg = sum((2.0**gain - 1.0) / math.log2(index + 2) for index, gain in enumerate(ideal))
    return float(dcg / idcg) if idcg else 0.0


def score_manual_review() -> None:
    import pandas as pd
    m = manual_paths()
    phase_a = load_csv(m["a"])
    phase_b = load_csv(m["b"])
    phase_a["problem_relevance_0_1_2"] = parse_rating(phase_a["problem_relevance_0_1_2"], "problem_relevance_0_1_2")
    phase_b["action_applicability_0_1_2"] = parse_rating(phase_b["action_applicability_0_1_2"], "action_applicability_0_1_2")
    private = read_private()
    full = phase_a.merge(private, on=["pair_id", "query_id"], how="left", validate="one_to_one")
    full = full.merge(phase_b[["pair_id", "action_applicability_0_1_2", "phase_b_label_source", "phase_b_notes"]], on="pair_id", how="left", validate="one_to_one")
    full["action_applicability_0_1_2"] = pd.to_numeric(full.action_applicability_0_1_2, errors="coerce").fillna(0).astype(int)
    rows = []
    for query_id, group in full.groupby("query_id"):
        group = group.sort_values("rank")
        relevant = (group.problem_relevance_0_1_2 >= 1).astype(int).to_numpy()
        useful = ((group.problem_relevance_0_1_2 >= 1) & (group.action_applicability_0_1_2 >= 1)).astype(int).to_numpy()
        rows.append({
            "query_id": query_id,
            "problem_relevant_at_1": int(relevant[:1].max()),
            "problem_relevant_at_3": int(relevant[:3].max()),
            "problem_relevant_at_5": int(relevant[:5].max()),
            "usable_action_evidence_at_1": int(useful[:1].max()),
            "usable_action_evidence_at_3": int(useful[:3].max()),
            "usable_action_evidence_at_5": int(useful[:5].max()),
            "ndcg_problem_relevance_at_5": ndcg(group),
        })
    per_query = pd.DataFrame(rows)
    relevant_mask = full.problem_relevance_0_1_2 >= 1
    metrics = {
        "version": VERSION,
        "created_utc": utc_now(),
        "selected_retrieval_mode": selected_configuration()[0],
        "selected_tau": selected_configuration()[2],
        "selected_aggregation": selected_configuration()[3],
        "reviewed_queries": int(per_query.query_id.nunique()),
        "reviewed_pairs": len(full),
        "phase_a": {
            "problem_relevance_hit_at_1": float(per_query.problem_relevant_at_1.mean()),
            "problem_relevance_hit_at_3": float(per_query.problem_relevant_at_3.mean()),
            "problem_relevance_hit_at_5": float(per_query.problem_relevant_at_5.mean()),
            "mean_ndcg_problem_relevance_at_5": float(per_query.ndcg_problem_relevance_at_5.mean()),
            "pairwise_relevant_or_partial_rate": float(relevant_mask.mean()),
            "clearly_relevant_pair_rate": float((full.problem_relevance_0_1_2 == 2).mean()),
        },
        "phase_b": {
            "problem_relevant_pairs_revealed": int(relevant_mask.sum()),
            "applicable_or_partial_rate_among_problem_relevant_pairs": float((full.loc[relevant_mask, "action_applicability_0_1_2"] >= 1).mean()) if relevant_mask.any() else None,
            "clearly_applicable_rate_among_problem_relevant_pairs": float((full.loc[relevant_mask, "action_applicability_0_1_2"] == 2).mean()) if relevant_mask.any() else None,
            "usable_historical_action_evidence_hit_at_1": float(per_query.usable_action_evidence_at_1.mean()),
            "usable_historical_action_evidence_hit_at_3": float(per_query.usable_action_evidence_at_3.mean()),
            "usable_historical_action_evidence_hit_at_5": float(per_query.usable_action_evidence_at_5.mean()),
        },
        "carry_forward": {
            "phase_a_pairs": int((full.phase_a_label_source == "carried_forward_raw_v1").sum()),
            "phase_b_pairs": int((full.get("phase_b_label_source", pd.Series(dtype=str)) == "carried_forward_raw_v1").sum()),
        },
        "interpretation": "Judgments concern relevance and usefulness of historical evidence; they do not validate technical correctness, safety, or regulatory applicability.",
        "single_reviewer_limitation": "Inter-rater agreement cannot be estimated when one reviewer is used.",
    }
    full.to_csv(m["scored"], index=False)
    per_query.to_csv(m["per_query"], index=False)
    atomic_json(m["results"], metrics)
    manifest = json.loads(m["manifest"].read_text(encoding="utf-8"))
    manifest.update({
        "status": "complete",
        "phase_a_final_sha256": sha256(m["a"]),
        "phase_b_final_sha256": sha256(m["b"]),
        "results_sha256": sha256(m["results"]),
    })
    atomic_json(m["manifest"], manifest)
    print(json.dumps(metrics, indent=2))
    print("SELECTIVE_MANUAL_REVIEW_COMPLETE")


def command_manual_next(_args) -> None:
    m = manual_paths()
    if m["results"].is_file():
        print(m["results"].read_text(encoding="utf-8"))
        print("SELECTIVE_MANUAL_REVIEW_ALREADY_COMPLETE")
        return
    if not m["a"].is_file():
        build_manual_pool()
        return
    phase_a = load_csv(m["a"])
    try:
        parse_rating(phase_a["problem_relevance_0_1_2"], "problem_relevance_0_1_2")
    except RuntimeError as exc:
        print(str(exc))
        print(f"Complete the blank Phase-A ratings and rerun the same BAT file: {m['a']}")
        print("SELECTIVE_MANUAL_WAITING_FOR_PHASE_A")
        return
    if not m["b"].is_file():
        reveal_manual_phase_b()
        return
    phase_b = load_csv(m["b"])
    try:
        parse_rating(phase_b["action_applicability_0_1_2"], "action_applicability_0_1_2")
    except RuntimeError as exc:
        print(str(exc))
        print(f"Complete the blank Phase-B ratings and rerun the same BAT file: {m['b']}")
        print("SELECTIVE_MANUAL_WAITING_FOR_PHASE_B")
        return
    score_manual_review()


def command_report(_args) -> None:
    p, m = paths(), manual_paths()
    require_files([
        p["audit"], p["dev"] / "RQ4_DEV_SELECTION.json",
        p["test"] / "RQ4_FINAL_TEST.json", p["rq5"] / "RQ5_PLANNING_SUPPORT.json",
    ])
    audit = json.loads(p["audit"].read_text(encoding="utf-8"))
    dev = json.loads((p["dev"] / "RQ4_DEV_SELECTION.json").read_text(encoding="utf-8"))
    test = json.loads((p["test"] / "RQ4_FINAL_TEST.json").read_text(encoding="utf-8"))
    rq5 = json.loads((p["rq5"] / "RQ5_PLANNING_SUPPORT.json").read_text(encoding="utf-8"))
    raw_test_path = p["raw_freeze"] / "rq4_case_retrieval" / "test" / "RQ4_FINAL_TEST.json"
    raw_test = json.loads(raw_test_path.read_text(encoding="utf-8")) if raw_test_path.is_file() else None
    manual = json.loads(m["results"].read_text(encoding="utf-8")) if m["results"].is_file() else None

    def row(label: str, metrics: dict[str, Any]) -> str:
        return (
            f"| {label} | {metrics['hit_at_1']:.4f} | {metrics['hit_at_3']:.4f} | "
            f"{metrics['mrr']:.4f} | {metrics['macro_action_family_recall']:.4f} |"
        )

    selected = test["selected_configuration_metrics"]
    tau0 = test["tau0_comparator_metrics"]
    representative = test["representative_ablation_metrics"]
    lines = [
        "# Selective-ByT5 RQ4/RQ5 thesis results",
        "",
        f"Generated: {utc_now()}",
        "",
        "## Frozen experimental identity",
        "",
        f"- Representation: Selective ByT5",
        f"- Records: {audit['records']:,}",
        f"- Split: {audit['split_counts']}",
        f"- Evidence clusters: {audit['evidence_clusters']:,}",
        f"- Leakage groups: {audit['leakage_groups']:,}",
        f"- Selected retrieval mode: `{dev['selected_mode']}`",
        f"- Selected prior temperature: `{dev['selected_tau']}`",
        f"- Aggregation: `{dev['selected_aggregation']}`",
        f"- Retrieval mode selection: {dev['mode_selection_rule']}",
        f"- Prior-temperature selection: {dev['tau_selection_rule']}",
        "- The retrieval query uses normalized PROBLEM text and problem-only Selective SpERT structure. ACTION is opened only after retrieval.",
        "- The earlier lexicon-only temperature sweep is treated as post-hoc scoping evidence; it is not a confirmatory result.",
        "",
        "## RQ4 locked-test automatic results",
        "",
        "| Configuration | Hit@1 | Hit@3 | MRR | Macro recall |",
        "|---|---:|---:|---:|---:|",
        row("DEV-selected complete system", selected),
        row("Same mode, tau=0", tau0),
        row("Representative-only action ablation", representative),
        "",
        f"Pattern-set recall@3: **{selected['pattern_set_recall_at_3']:.4f}**  ",
        f"Pattern-set recall@5: **{selected['pattern_set_recall_at_5']:.4f}**  ",
        f"Recorded multi-family set recall@3: **{selected['recorded_multi_family_set_recall_at_3']:.4f}**  ",
        f"Answer rate: **{selected['answer_rate']:.4f}**",
        f"Selected Hit@1 95% bootstrap CI: **{test['selected_bootstrap_intervals']['hit_at_1_95ci']}**  ",
        f"Selected macro-recall 95% stratified-bootstrap CI: **{test['selected_bootstrap_intervals']['macro_recall_95ci']}**  ",
        f"Selected-vs-tau0 Hit@1 difference: **{test['selected_vs_tau0']['selected_minus_tau0_hit_at_1']:.4f}**; "
        f"McNemar exact p = **{test['selected_vs_tau0']['mcnemar_exact_two_sided_p']:.4f}**.",
        "",
        "The primary metrics measure agreement with recorded historical action families. They do not measure technical correctness, safety, regulatory applicability, or airworthiness.",
        "",
        "## Per-family locked-test Hit@1",
        "",
        "| Family | Queries | Hit@1 |",
        "|---|---:|---:|",
    ]
    for family, values in selected.get("per_family", {}).items():
        lines.append(f"| {family} | {values['queries']} | {values['hit_at_1']:.4f} |")
    lines += [
        "",
        "## RQ5 historical-agreement calibration",
        "",
        f"- ECE (10 bins): {rq5['ece_10_bins']:.4f}",
        f"- Brier score: {rq5['brier_score']:.4f}",
        "- Calibration was fitted on DEV and evaluated on locked TEST.",
        "- Lower-probability, single-support and nearest-only evidence remains visible; probability is a grade, not a display gate.",
    ]
    if manual:
        lines += [
            "",
            "## Blinded manual review",
            "",
            f"- Queries: {manual['reviewed_queries']}",
            f"- Pairs: {manual['reviewed_pairs']}",
            f"- Problem relevance Hit@1: {manual['phase_a']['problem_relevance_hit_at_1']:.4f}",
            f"- Problem relevance Hit@5: {manual['phase_a']['problem_relevance_hit_at_5']:.4f}",
            f"- Usable action evidence Hit@1: {manual['phase_b']['usable_historical_action_evidence_hit_at_1']:.4f}",
            f"- Usable action evidence Hit@5: {manual['phase_b']['usable_historical_action_evidence_hit_at_5']:.4f}",
            "- With one reviewer, inter-rater agreement cannot be estimated.",
        ]
    if raw_test:
        old = raw_test["selected_mode_metrics"]
        lines += [
            "",
            "## Original raw frozen run — contextual reference only",
            "",
            "| Run | Hit@1 | Hit@3 | MRR | Macro recall |",
            "|---|---:|---:|---:|---:|",
            row("Original raw/TRUE-RAW-SpERT freeze", old),
            row("New Selective complete system", selected),
            "",
            "**Comparison limitation:** the Selective protocol rebuilds canonical clusters and leakage groups, so its TEST partition is not identical to the original raw TEST partition. The table is descriptive, not a paired causal estimate of normalization benefit.",
        ]
    lines += [
        "",
        "## Evidence-presentation safeguards",
        "",
        "- Cluster-expanded actions are grouped into `(family, component, fault)` patterns.",
        "- Every cluster contributes at most one vote per family and pattern.",
        "- Single-cluster actions are displayed as Limited historical evidence.",
        "- Positive, unknown, negative and mixed outcomes remain distinguishable.",
        "- Historical work-order IDs and raw/normalized text provide provenance.",
        "- The system presents evidence and alternatives; it does not generate or approve a maintenance procedure.",
        "",
    ]
    destination = p["run"] / "SELECTIVE_RQ4_RQ5_THESIS_RESULTS.md"
    atomic_text(destination, "\n".join(lines))
    print(f"WROTE {destination}")
    print("SELECTIVE_THESIS_REPORT_COMPLETE")


def command_freeze(_args) -> None:
    p, m = paths(), manual_paths()
    if p["frozen"].exists():
        print(f"Selective freeze already exists: {p['frozen']}")
        command_verify(argparse.Namespace())
        return
    require_files([
        p["test_lock"], p["test"] / "RQ4_FINAL_TEST.json",
        p["rq5"] / "RQ5_PLANNING_SUPPORT.json", m["results"], m["manifest"],
    ])
    # Fail before creating a candidate freeze if the preserved raw evidence has
    # changed.  This keeps the original frozen run authoritative and avoids a
    # partially published Selective freeze on verification failure.
    verify_checksum_manifest(p["raw_freeze"])
    command_report(_args)
    stage = p["frozen"].with_name(p["frozen"].name + ".staging-" + dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
    stage.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(p["run"], stage / "rq4_case_retrieval_selective_v2")
    shutil.copytree(p["rq5"], stage / "rq5_planning_support_selective_v2")
    raw_sums = p["raw_freeze"] / "SHA256SUMS.txt"
    manifest = {
        "version": VERSION,
        "created_utc": utc_now(),
        "status": "complete",
        "representation": "selective_byt5",
        "training_performed": False,
        "thesis_rq4": "leakage-safe Selective-ByT5 historical-case retrieval",
        "thesis_rq5": "DEV-calibrated auditable planning support",
        "no_post_test_tuning": True,
        "problem_only_retrieval": True,
        "action_used_for_retrieval_or_clustering": False,
        "selected_configuration": {
            "retrieval_mode": selected_configuration()[0],
            "tau": selected_configuration()[2],
            "aggregation": selected_configuration()[3],
        },
        "single_support_visibility": "Limited historical evidence is retained; no tight display gate.",
        "negative_mixed_policy": "Preserved separately and excluded from corroborating support.",
        "preserved_raw_freeze": str(p["raw_freeze"]),
        "preserved_raw_freeze_sums_sha256": sha256(raw_sums),
        "run_identity": run_identity(),
    }
    atomic_json(stage / "FREEZE_MANIFEST.json", manifest)
    checksums = []
    for file in sorted(stage.rglob("*")):
        if file.is_file() and file.name != "SHA256SUMS.txt":
            checksums.append(f"{sha256(file)}  {file.relative_to(stage).as_posix()}")
    atomic_text(stage / "SHA256SUMS.txt", "\n".join(checksums) + "\n", encoding="ascii")
    # Verify the complete staging tree before the atomic directory rename.
    verify_checksum_manifest(stage)
    os.replace(stage, p["frozen"])
    print(f"FROZEN {p['frozen']} files={len(checksums)}")
    command_verify(argparse.Namespace())


def command_verify(_args) -> None:
    p = paths()
    require_files([p["frozen"] / "FREEZE_MANIFEST.json", p["frozen"] / "SHA256SUMS.txt"])
    manifest = json.loads((p["frozen"] / "FREEZE_MANIFEST.json").read_text(encoding="utf-8"))
    if manifest.get("version") != VERSION or manifest.get("representation") != "selective_byt5":
        raise RuntimeError("Selective freeze manifest identity mismatch.")
    failures = []
    for line in (p["frozen"] / "SHA256SUMS.txt").read_text(encoding="ascii").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split("  ", 1)
        file = p["frozen"] / Path(relative)
        if not file.is_file() or sha256(file) != expected:
            failures.append(relative)
    current_raw = sha256(p["raw_freeze"] / "SHA256SUMS.txt")
    if current_raw != manifest.get("preserved_raw_freeze_sums_sha256"):
        failures.append("preserved raw final_rq4_rq5/SHA256SUMS.txt")
    try:
        verify_checksum_manifest(p["raw_freeze"])
    except RuntimeError as exc:
        failures.append(str(exc))
    if failures:
        raise RuntimeError("Freeze verification failed: " + ", ".join(failures[:10]))
    print(json.dumps({
        "status": "verified",
        "version": VERSION,
        "freeze": str(p["frozen"]),
        "checksummed_files": len((p["frozen"] / "SHA256SUMS.txt").read_text(encoding="ascii").splitlines()),
        "raw_freeze_unchanged": True,
    }, indent=2))
    print("SELECTIVE_RQ4_RQ5_FREEZE_VERIFIED")


def status_value() -> dict[str, Any]:
    p, m = paths(), manual_paths()
    phase = "not_started"
    if m["results"].is_file():
        phase = "complete"
    elif m["b"].is_file():
        phase = "phase_b_ready"
    elif m["a"].is_file():
        phase = "phase_a_ready"
    return {
        "version": VERSION,
        "prepared": p["audit"].is_file(),
        "problem_only_predictions": p["pred_manifest"].is_file(),
        "rq4_dev": (p["dev"] / "RQ4_DEV_SELECTION.json").is_file(),
        "rq4_test_locked": p["test_lock"].is_file(),
        "rq5_calibrated": (p["rq5"] / "RQ5_PLANNING_SUPPORT.json").is_file(),
        "manual_review": phase,
        "frozen": p["frozen"].is_dir(),
        "thesis_report": (p["run"] / "SELECTIVE_RQ4_RQ5_THESIS_RESULTS.md").is_file(),
        "run_root": str(p["run"]),
        "freeze_root": str(p["frozen"]),
    }


def command_status(args) -> None:
    value = status_value()
    print(json.dumps(value, indent=None if args.json else 2))


def command_self_test(_args) -> None:
    assert canonical_problem_key("#2 INTAKE LEAKING") == "num_2 intake leaking"
    assert canonical_problem_key("NUMBER TWO INTAKES LEAKING") == "num_2 intake leaking"
    assert canonical_problem_key("L/H CYL #4 20/80 PSI") == "left cylinder num_4 ratio_20_80 psi"
    assert canonical_problem_key("R/H CYLINDER NUMBER 4 20 / 80 PSI") == "right cylinder num_4 ratio_20_80 psi"
    assert set(PUBLIC_MODES.values()) == {"raw_bm25", "norm_bm25", "norm_tfidf", "structure", "weighted_hybrid", "rrf_hybrid"}
    assert stable_id("X-", "same") == stable_id("X-", "same")
    print("SELECTIVE_RQ4_RQ5_SELF_TEST_OK")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Versioned Selective-ByT5 RQ4/RQ5 pipeline")
    sub = root.add_subparsers(dest="command", required=True)
    p = sub.add_parser("preflight")
    p.add_argument("--static-only", action="store_true")
    p.add_argument("--no-write", action="store_true")
    sub.add_parser("prepare")
    p = sub.add_parser("precompute")
    p.add_argument("--cpu", action="store_true")
    p = sub.add_parser("evaluate")
    p.add_argument("--partition", choices=["dev", "test"], required=True)
    p.add_argument("--confirm-final-test", action="store_true")
    sub.add_parser("rq5")
    sub.add_parser("manual-next")
    sub.add_parser("report")
    sub.add_parser("freeze")
    sub.add_parser("verify")
    p = sub.add_parser("status")
    p.add_argument("--json", action="store_true")
    sub.add_parser("self-test")
    return root


def main() -> int:
    root_path = dashboard_root()
    if str(root_path) not in sys.path:
        sys.path.insert(0, str(root_path))
    args = parser().parse_args()
    commands = {
        "preflight": command_preflight,
        "prepare": command_prepare,
        "precompute": command_precompute,
        "evaluate": command_evaluate,
        "rq5": command_rq5,
        "manual-next": command_manual_next,
        "report": command_report,
        "freeze": command_freeze,
        "verify": command_verify,
        "status": command_status,
        "self-test": command_self_test,
    }
    try:
        commands[args.command](args)
        return 0
    except (RuntimeError, FileNotFoundError, KeyError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
