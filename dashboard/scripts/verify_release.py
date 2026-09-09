from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def find_weight(directory: Path, names: list[str]) -> Path | None:
    for name in names:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the AviMaint-DSS deployment bundle")
    parser.add_argument("--require-models", action="store_true")
    parser.add_argument("--require-frontend", action="store_true", help="also require and inspect a completed frontend build")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "data" / "release_manifest.json").read_text(encoding="utf-8"))
    deployment = json.loads((ROOT / "config" / "deployment.json").read_text(encoding="utf-8"))
    frontend_package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    versions = {manifest.get("version"), deployment.get("version"), frontend_package.get("version")}
    if versions != {"8.3.2"}:
        raise SystemExit(f"FAILED release version mismatch: {sorted(str(value) for value in versions)}")
    for relative, expected in manifest["files"].items():
        path = ROOT / "data" / relative
        if not path.is_file() or sha256(path) != expected:
            raise SystemExit(f"FAILED checksum: {relative}")

    cases_path = ROOT / "data" / "selective_cases_final.csv"
    required = {
        "IDENT", "problem_raw", "action_raw", "problem_normalized", "action_normalized",
        "problem_retrieval_key", "action_family", "outcome", "evidence_cluster_id",
        "leakage_group_id", "split",
    }
    counts = Counter(); identities = set(); groups = defaultdict(set); clusters = defaultdict(set)
    with cases_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"FAILED missing case columns: {sorted(missing)}")
        for row in reader:
            ident = row["IDENT"]
            if ident in identities:
                raise SystemExit(f"FAILED duplicate IDENT: {ident}")
            identities.add(ident); counts[row["split"]] += 1
            groups[row["leakage_group_id"]].add(row["split"])
            clusters[row["evidence_cluster_id"]].add(row["split"])
            if not row["problem_normalized"].strip() or not row["action_normalized"].strip():
                raise SystemExit(f"FAILED empty normalized text: {ident}")
    if len(identities) != 6169 or counts != Counter({"train": 4319, "dev": 925, "test": 925}):
        raise SystemExit(f"FAILED corpus counts: records={len(identities)} splits={dict(counts)}")
    if any(len(value) != 1 for value in groups.values()) or any(len(value) != 1 for value in clusters.values()):
        raise SystemExit("FAILED split leakage check")

    prediction_ids = set()
    with (ROOT / "data" / "predictions_problem_only_selective.jsonl").open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                prediction_ids.add(str(json.loads(line)["ident"]))
    if prediction_ids != identities:
        raise SystemExit("FAILED prediction coverage")

    dist = ROOT / "frontend" / "dist"
    frontend_built = (dist / "index.html").is_file()
    if args.require_frontend and not frontend_built:
        raise SystemExit("FAILED frontend dist is missing")
    # Inspect generated chunks only for an explicit post-build verification.
    # The Windows launcher may be run over an older extracted release whose
    # dist directory is stale; Docker always builds a fresh frontend.
    if args.require_frontend and frontend_built:
        for page in ("DiagnosePage", "OverviewPage", "InsightsPage", "KnowledgeGraphPage", "PlanningPage", "EvaluationPage", "GuidePage"):
            chunks = list((dist / "assets").glob(f"{page}-*.js"))
            if len(chunks) != 1:
                raise SystemExit(f"FAILED stale or missing frontend chunks for {page}: {len(chunks)}")

    model_manifest = json.loads((ROOT / "models" / "manifest.json").read_text(encoding="utf-8"))
    model_status = []
    for model in model_manifest["optional_live_models"]:
        directory = ROOT / model["destination"]
        weight = find_weight(directory, model["weight_files_any"])
        present = bool(weight)
        if present and sha256(weight) != model["weight_sha256"]:
            raise SystemExit(f"FAILED model checksum: {model['id']}")
        if args.require_models and not present:
            raise SystemExit(f"FAILED optional model required but missing: {model['id']}")
        model_status.append({"id": model["id"], "present": present})

    print(json.dumps({
        "status": "verified",
        "version": manifest["version"],
        "records": len(identities),
        "splits": dict(counts),
        "leakage_group_crossings": 0,
        "evidence_cluster_crossings": 0,
        "prediction_coverage": len(prediction_ids),
        "frontend_built": frontend_built,
        "default_neural_models_required": 0,
        "operational_policy": deployment["operational_action_matching"],
        "optional_models": model_status,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
