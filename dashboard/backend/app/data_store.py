from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pandas as pd

from .settings import Settings
from .terminology import (
    ACTION_FAMILIES,
    canonical_component,
    display_problem_key,
    issue_family,
    merge_components,
    normalized_locations,
    stable_display_group,
    target_component,
)


EXPECTED_CASES_SHA256 = "ad5b5771ae4c41b60402128fc9c99c6e59d87f4af332864a205106a85db30be2"
EXPECTED_PREDICTIONS_SHA256 = "bb5dcdd7246c1e3220f1fefc6f092591f99d6fb3874ac1a258bb9734bb7a8a15"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_predictions(path: Path) -> dict[str, dict]:
    predictions: dict[str, dict] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            ident = str(row.get("ident") or "")
            if not ident or ident in predictions:
                raise RuntimeError(f"Invalid prediction identity at line {line_no}")
            predictions[ident] = row.get("problem_pred") or {}
    return predictions


def _structures(problem: str, prediction: dict) -> tuple[list[str], list[str], list[str], list[dict], list[dict]]:
    raw_entities = prediction.get("entities") or []
    learned_components = [
        canonical_component(entity.get("text", ""))
        for entity in raw_entities if entity.get("type") == "MAINT_ITEM"
    ]
    components = merge_components(problem, learned_components)
    faults: list[str] = []
    for entity in raw_entities:
        if entity.get("type") not in {"FAULT", "ABN_PROC", "TECH_OBS"}:
            continue
        label = issue_family(str(entity.get("text") or ""))
        if label and label not in faults:
            faults.append(label)
    whole_fault = issue_family(problem)
    if whole_fault and whole_fault not in faults:
        faults.append(whole_fault)
    learned_locations = [
        str(entity.get("text") or "").strip().lower()
        for entity in raw_entities if entity.get("type") == "LOC" and str(entity.get("text") or "").strip()
    ]
    locations = normalized_locations(problem, learned_locations)
    entities = [
        {
            "type": str(entity.get("type") or "ENTITY"),
            "text": str(entity.get("text") or ""),
            "start": entity.get("start"), "end": entity.get("end"),
            "score": round(float(entity.get("score") or 0.0), 4),
        }
        for entity in raw_entities
    ]
    relations = []
    for relation in prediction.get("relations") or []:
        head = relation.get("head")
        tail = relation.get("tail")
        item = {
            "type": str(relation.get("type") or "RELATION"),
            "head": head, "tail": tail,
            "score": round(float(relation.get("score") or 0.0), 4),
        }
        relations.append(item)
    return components, faults, list(dict.fromkeys(locations)), entities, relations


class DataStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        cases_path = settings.data_dir / "selective_cases_final.csv"
        predictions_path = settings.data_dir / "predictions_problem_only_selective.jsonl"
        if sha256(cases_path) != EXPECTED_CASES_SHA256:
            raise RuntimeError("Selective case file does not match the frozen final identity")
        if sha256(predictions_path) != EXPECTED_PREDICTIONS_SHA256:
            raise RuntimeError("Selective SpERT predictions do not match the frozen final identity")
        frame = pd.read_csv(cases_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        if len(frame) != 6169 or frame["IDENT"].nunique() != 6169:
            raise RuntimeError("Expected 6,169 unique Selective records")
        if frame["split"].value_counts().to_dict() != {"train": 4319, "test": 925, "dev": 925}:
            raise RuntimeError("Selective split counts changed")
        predictions = _read_predictions(predictions_path)
        if set(predictions) != set(frame["IDENT"].astype(str)):
            raise RuntimeError("Precomputed Selective SpERT predictions do not cover the corpus")

        components: list[list[str]] = []
        faults: list[list[str]] = []
        locations: list[list[str]] = []
        entities: list[list[dict]] = []
        relations: list[list[dict]] = []
        for row in frame.itertuples(index=False):
            structure = _structures(str(row.problem_normalized), predictions[str(row.IDENT)])
            components.append(structure[0]); faults.append(structure[1]); locations.append(structure[2])
            entities.append(structure[3]); relations.append(structure[4])

        frame = frame.assign(
            ident=frame["IDENT"].astype(str),
            problem=frame["problem_normalized"].astype(str),
            action=frame["action_normalized"].astype(str),
            problem_norm=frame["problem_retrieval_key"].astype(str),
            cluster_id=frame["evidence_cluster_id"].astype(str),
            frozen_split=frame["split"].astype(str),
            components=components, faults=faults, locations=locations,
            problem_entities=entities, problem_relations=relations,
        )
        frame["component"] = frame["components"].map(lambda values: target_component(values) or "(unspecified)")
        frame["fault"] = [issue_family(problem) or (values[0] if values else "(unspecified)") for problem, values in zip(frame["problem"], frame["faults"])]
        frame["display_key"] = frame["problem"].map(display_problem_key)
        frame["display_group_id"] = frame["problem"].map(stable_display_group)
        self.df = frame
        self.train = frame[frame["frozen_split"] == "train"].reset_index(drop=True)
        self.cluster_members = {
            str(cluster): indices.tolist()
            for cluster, indices in self.train.groupby("cluster_id").groups.items()
        }
        self.family_priors = self._family_priors()

    def _family_priors(self) -> dict[str, float]:
        supports = {
            (str(row.cluster_id), str(row.action_family))
            for row in self.train.itertuples(index=False)
            if str(row.action_family) != "Other" and str(row.outcome) not in {"negative", "mixed"}
        }
        counts = Counter(family for _cluster, family in supports)
        families = [family for family in ACTION_FAMILIES if counts.get(family)]
        denominator = sum(counts[family] for family in families) + len(families)
        return {family: (counts[family] + 1.0) / denominator for family in families}
