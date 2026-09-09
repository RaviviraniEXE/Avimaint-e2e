from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher

import numpy as np
from rank_bm25 import BM25Okapi

from .calibration import AgreementCalibrator
from .data_store import DataStore
from .settings import Settings
from .terminology import (
    canonical_component,
    canonical_problem_key,
    display_location,
    find_components,
    issue_family,
    looks_truncated,
    normalized_locations,
    normalize_query_for_display,
    target_component,
)


_TOKEN = re.compile(r"[a-z0-9_]+")


def tokenize(value: str) -> list[str]:
    return _TOKEN.findall(str(value or "").lower())


@dataclass(frozen=True)
class Hit:
    idx: int
    score: float
    raw_score: float
    match_level: str = "broader"
    rank_score: float = 0.0


class SelectiveRetriever:
    def __init__(self, store: DataStore, settings: Settings, calibrator: AgreementCalibrator):
        self.store = store
        self.settings = settings
        self.calibrator = calibrator
        self.docs = store.train["problem_norm"].astype(str).tolist()
        self.bm25 = BM25Okapi([tokenize(value) for value in self.docs])

    def search(self, query_key: str, top_k: int | None = None) -> list[Hit]:
        depth = int(top_k or self.settings.retrieval_depth)
        raw = np.asarray(self.bm25.get_scores(tokenize(query_key)), dtype=float)
        minimum = float(raw.min()) if raw.size else 0.0
        maximum = float(raw.max()) if raw.size else 0.0
        scores = (raw - minimum) / (maximum - minimum) if maximum - minimum > 1e-12 else np.zeros_like(raw)
        hits: list[Hit] = []
        used_clusters: set[str] = set()
        for idx in np.argsort(-scores):
            cluster = str(self.store.train.iloc[int(idx)].cluster_id)
            if cluster in used_clusters:
                continue
            used_clusters.add(cluster)
            hits.append(Hit(int(idx), float(scores[idx]), float(raw[idx])))
            if len(hits) >= depth:
                break
        return hits

    @staticmethod
    def _case(row, score: float, match_level: str = "broader") -> dict:
        family = str(row.action_family)
        outcome = str(row.outcome)
        return {
            "ident": str(row.ident),
            "problem": str(row.problem),
            "problem_raw": str(row.problem_raw),
            "problem_may_be_truncated": looks_truncated(str(row.problem)),
            "action": str(row.action),
            "action_raw": str(row.action_raw),
            "action_may_be_truncated": looks_truncated(str(row.action)),
            "action_family": family,
            "action_kind": "assessment documented" if family in {"Inspect", "Diagnose"} else "corrective action documented" if family != "Other" else "unclassified action text",
            "outcome": outcome,
            "outcome_label": "resolved outcome recorded" if outcome == "positive" else "did not resolve / mixed outcome recorded" if outcome in {"negative", "mixed"} else "post-action outcome not recorded",
            "cluster_id": str(row.cluster_id),
            "score": round(float(score), 8),
            "text_score": round(float(score), 8),
            "structure_score": 0.0,
            "channels": {"canonical_bm25": round(float(score), 8)},
            "match_level": match_level,
        }

    @staticmethod
    def _action_sentence(
        family: str,
        target: str,
        query_locations: list[str] | None = None,
        query_component: str = "",
    ) -> str:
        verb = {
            "Replace": "Replace", "Repair": "Repair", "Inspect": "Inspect",
            "Adjust": "Adjust", "Service": "Service", "Diagnose": "Diagnose",
            "Calibrate": "Calibrate",
        }.get(family, "Review")
        subject = target or "reported component"
        # Retarget position-specific evidence to the reported position only
        # when the action target is the queried component (or its explicit
        # sub-part, such as intake -> intake gasket). A different target such
        # as a spark plug remains a separate, unretargeted option.
        locations = list(query_locations or [])
        same_target = bool(query_component) and (
            subject == query_component or query_component in subject or subject in query_component
        )
        if locations and same_target:
            qualifier = " ".join(display_location(value) for value in locations)
            subject = f"{qualifier} {subject}"
        return f"{verb} the {subject}."

    @staticmethod
    def _contextual_action_target(action_target: str, query_component: str, family: str) -> str:
        if action_target == "gasket" and family in {"Replace", "Repair", "Inspect"}:
            if query_component.endswith("gasket"):
                return query_component
            if query_component in {"intake", "rocker cover"}:
                return f"{query_component} gasket"
        return action_target or query_component

    @staticmethod
    def _structure_signature(entities: list[dict], relations: list[dict]) -> tuple[tuple, tuple]:
        """Return a score-free, order-stable signature of a frozen SpERT graph."""
        entity_keys = [
            (str(entity.get("type") or "ENTITY"), canonical_problem_key(str(entity.get("text") or "")))
            for entity in entities
        ]
        relation_keys = []
        for relation in relations:
            head = relation.get("head")
            tail = relation.get("tail")
            head_key = entity_keys[head] if isinstance(head, int) and 0 <= head < len(entity_keys) else ("", "")
            tail_key = entity_keys[tail] if isinstance(tail, int) and 0 <= tail < len(entity_keys) else ("", "")
            relation_keys.append((str(relation.get("type") or "RELATION"), head_key, tail_key))
        return tuple(sorted(entity_keys)), tuple(sorted(relation_keys))

    @staticmethod
    def _adapter_relations(entities: list[dict], target: str) -> list[dict]:
        """Build transparent schema relations for unseen query wording.

        These are deterministic links between extracted anchors, not SpERT
        predictions and not a calibrated confidence claim.
        """
        component_indices = [
            index for index, entity in enumerate(entities)
            if entity.get("type") == "MAINT_ITEM"
        ]
        target_index = next(
            (
                index for index in component_indices
                if canonical_problem_key(str(entities[index].get("text") or "")) == canonical_problem_key(target)
            ),
            component_indices[-1] if component_indices else None,
        )
        if target_index is None:
            return []
        relations: list[dict] = []
        for index, entity in enumerate(entities):
            kind = str(entity.get("type") or "")
            if kind == "LOC":
                relations.append({"type": "HAS_LOCATION", "head": target_index, "tail": index, "source": "deterministic_schema_adapter"})
            elif kind in {"FAULT", "ABN_PROC", "TECH_OBS"}:
                relations.append({"type": "ISSUE_ON_ITEM", "head": index, "tail": target_index, "source": "deterministic_schema_adapter"})
        return relations

    def _query_structure(
        self,
        query_key: str,
        fallback_entities: list[dict],
        target: str,
        force_adapter: bool = False,
    ) -> tuple[list[dict], list[dict], str, tuple[tuple, tuple] | None]:
        """Reuse a frozen TRAIN prediction only when the normalized problem text is exact.

        This keeps action retrieval TRAIN-only and avoids pretending that the hosted
        deterministic adapter produced SpERT relations for unseen wording.
        """
        if force_adapter:
            return fallback_entities, self._adapter_relations(fallback_entities, target), "deterministic_schema_adapter_user_corrected", None
        exact = self.store.train[self.store.train["problem_norm"] == query_key]
        if exact.empty:
            return fallback_entities, self._adapter_relations(fallback_entities, target), "deterministic_schema_adapter", None
        row = exact.iloc[0]
        entities = list(row.problem_entities)
        relations = list(row.problem_relations)
        return entities, relations, "frozen_train_exact_text_prediction", self._structure_signature(entities, relations)

    def _match_signature(
        self,
        row,
        query_component: str,
        query_faults: list[str],
        query_locations: list[str],
        query_structure_signature: tuple[tuple, tuple] | None = None,
    ) -> tuple[bool, float, str]:
        candidate_component = target_component(list(row.components))
        component_match = bool(query_component) and candidate_component == query_component
        fault_match = bool(query_faults) and bool(set(query_faults) & set(row.faults))
        query_has_position = bool(query_locations)
        location_match = query_has_position and set(row.locations) == set(query_locations)
        matched = int(component_match) + int(fault_match) + int(location_match)
        eligible = component_match and fault_match
        full_structure = bool(
            eligible and query_structure_signature is not None
            and self._structure_signature(list(row.problem_entities), list(row.problem_relations)) == query_structure_signature
        )
        if full_structure:
            label = "full entity-relation match"
        elif eligible and not query_has_position:
            label = "same component and fault · query position not specified"
        elif eligible and location_match:
            label = "same component and fault · same position"
        elif eligible and row.locations:
            label = "same component and fault · other position"
        elif eligible:
            label = "same component and fault · position not recorded"
        else:
            label = f"{matched}/3 anchors matched"
        # Component and fault are gates. Position is a preference, not a gate.
        anchor_score = 1.0 if eligible and location_match else 0.82 if eligible and (row.locations or not query_has_position) else 0.72 if eligible else matched / 3.0
        return eligible, anchor_score, label

    def search_operational(
        self,
        query_key: str,
        query_components: list[str],
        query_faults: list[str],
        query_locations: list[str],
        query_structure_signature: tuple[tuple, tuple] | None,
        top_k: int,
    ) -> tuple[list[Hit], list[Hit]]:
        raw = np.asarray(self.bm25.get_scores(tokenize(query_key)), dtype=float)
        minimum = float(raw.min()) if raw.size else 0.0
        maximum = float(raw.max()) if raw.size else 0.0
        scores = (raw - minimum) / (maximum - minimum) if maximum - minimum > 1e-12 else np.zeros_like(raw)
        query_component = target_component(query_components)
        ranked: list[Hit] = []
        for idx, score in enumerate(scores):
            row = self.store.train.iloc[idx]
            eligible, anchor_score, label = self._match_signature(
                row, query_component, query_faults, query_locations, query_structure_signature
            )
            length_gap = max(0, len(tokenize(self.docs[idx])) - len(tokenize(query_key)))
            operational_score = float(score) + anchor_score - min(0.20, length_gap * 0.01)
            ranked.append(Hit(idx, float(score), float(raw[idx]), label, operational_score))
        ranked.sort(key=lambda hit: (-hit.rank_score, -hit.score, hit.idx))

        strict_hits: list[Hit] = []
        nearest_hits: list[Hit] = []
        used_strict: set[str] = set()
        used_nearest: set[str] = set()
        for hit in ranked:
            cluster = str(self.store.train.iloc[hit.idx].cluster_id)
            if cluster not in used_nearest and len(nearest_hits) < 10:
                used_nearest.add(cluster)
                nearest_hits.append(hit)
            if (hit.match_level == "full entity-relation match" or hit.match_level.startswith("same component and fault")) and cluster not in used_strict:
                used_strict.add(cluster)
                strict_hits.append(hit)
                if len(strict_hits) >= top_k and len(nearest_hits) >= 10:
                    break
        return strict_hits, nearest_hits

    @staticmethod
    def _distinct_clusters(examples: list[dict], limit: int) -> list[dict]:
        selected = []
        used = set()
        for example in examples:
            cluster = example["cluster_id"]
            if cluster in used:
                continue
            used.add(cluster)
            selected.append(example)
            if len(selected) >= limit:
                break
        return selected

    def _aggregate(
        self,
        hits: list[Hit],
        query_components: list[str],
        query_faults: list[str],
        query_locations: list[str],
    ) -> dict:
        patterns: dict[str, dict] = {}
        negative: list[dict] = []
        unclassified: list[dict] = []
        expanded_seen: set[int] = set()
        for hit in hits:
            cluster = str(self.store.train.iloc[hit.idx].cluster_id)
            for idx in self.store.cluster_members.get(cluster, [hit.idx]):
                if idx in expanded_seen:
                    continue
                expanded_seen.add(idx)
                row = self.store.train.iloc[idx]
                family = str(row.action_family)
                outcome = str(row.outcome)
                query_component = target_component(query_components)
                action_components = find_components(str(row.action))
                action_target = target_component(action_components) or target_component(list(row.components))
                if query_component == "intake" and "gasket" in action_components:
                    action_target = "intake gasket"
                elif query_component == "rocker cover" and "gasket" in action_components:
                    action_target = "rocker cover gasket"
                action_target = self._contextual_action_target(action_target, query_component, family)
                pattern_key = f"{family}|{action_target}"
                example = self._case(row, hit.score, hit.match_level)
                if family == "Other":
                    unclassified.append(example)
                    continue
                bucket = patterns.setdefault(pattern_key, {
                    "family": family, "target": action_target, "clusters": {}, "all_clusters": set(),
                    "same_position_clusters": set(), "other_position_clusters": set(),
                    "position_not_recorded_clusters": set(), "query_position_unspecified_clusters": set(), "full_structure_clusters": set(),
                    "outcome_cases": Counter(), "position_cases": Counter(), "other_positions": Counter(), "examples": [],
                })
                bucket["all_clusters"].add(cluster)
                bucket["outcome_cases"][outcome] += 1
                if not query_locations:
                    bucket["position_cases"]["query_unspecified"] += 1
                elif "same position" in hit.match_level or hit.match_level == "full entity-relation match":
                    bucket["position_cases"]["same"] += 1
                elif "other position" in hit.match_level:
                    bucket["position_cases"]["other"] += 1
                    for position in row.locations:
                        bucket["other_positions"][display_location(position)] += 1
                else:
                    bucket["position_cases"]["not_recorded"] += 1
                bucket["examples"].append(example)
                if outcome in {"negative", "mixed"}:
                    negative.append(example)
                    continue
                bucket["clusters"][cluster] = max(bucket["clusters"].get(cluster, 0.0), hit.score)
                if not query_locations:
                    bucket["query_position_unspecified_clusters"].add(cluster)
                elif "same position" in hit.match_level or hit.match_level == "full entity-relation match":
                    bucket["same_position_clusters"].add(cluster)
                elif "other position" in hit.match_level:
                    bucket["other_position_clusters"].add(cluster)
                else:
                    bucket["position_not_recorded_clusters"].add(cluster)
                if hit.match_level == "full entity-relation match":
                    bucket["full_structure_clusters"].add(cluster)

        rows = []
        for pattern_key, bucket in patterns.items():
            family = bucket["family"]
            support = len(bucket["clusters"])
            prior = max(self.store.family_priors.get(family, 0.0), 1e-12)
            rows.append({
                "family": family,
                "action_target": bucket["target"],
                "suggestion": self._action_sentence(family, bucket["target"], query_locations, target_component(query_components)),
                "support_clusters": support,
                "matching_clusters": len(bucket["all_clusters"]),
                "same_position_clusters": len(bucket["same_position_clusters"]),
                "other_position_clusters": len(bucket["other_position_clusters"]),
                "position_not_recorded_clusters": len(bucket["position_not_recorded_clusters"]),
                "query_position_unspecified_clusters": len(bucket["query_position_unspecified_clusters"]),
                "full_structure_support_clusters": len(bucket["full_structure_clusters"]),
                "case_count": len(bucket["examples"]),
                "same_position_cases": int(bucket["position_cases"]["same"]),
                "other_position_cases": int(bucket["position_cases"]["other"]),
                "position_not_recorded_cases": int(bucket["position_cases"]["not_recorded"]),
                "query_position_unspecified_cases": int(bucket["position_cases"]["query_unspecified"]),
                "other_positions": [
                    {"position": position, "cases": int(count)}
                    for position, count in bucket["other_positions"].most_common(8)
                ],
                "score_sum": float(sum(bucket["clusters"].values())),
                "prior": prior,
                "adjusted_support": support / (prior ** self.settings.selected_tau),
                "outcome_positive": int(bucket["outcome_cases"]["positive"]),
                "outcome_unknown": int(bucket["outcome_cases"]["unknown"]),
                "outcome_negative": int(bucket["outcome_cases"]["negative"] + bucket["outcome_cases"]["mixed"]),
                "examples": self._distinct_clusters(
                    sorted(bucket["examples"], key=lambda item: (-item["score"], item["ident"])), 8
                ),
            })
        # Operational presentation ranks repeated exact-match action patterns first.
        # The frozen RQ4 family vote and its metrics remain unchanged in research artifacts.
        rows.sort(key=lambda item: (-item["support_clusters"], -item["same_position_clusters"], -item["adjusted_support"], -item["score_sum"], -item["outcome_positive"], item["family"], item["action_target"]))
        comparable_cases = sum(item["case_count"] for item in rows)
        for item in rows:
            item["share_of_comparable_cases"] = item["case_count"] / comparable_cases if comparable_cases else 0.0
        top = rows[0]["support_clusters"] if rows else 0.0
        second = rows[1]["support_clusters"] if len(rows) > 1 else 0.0
        return {
            "patterns": rows,
            "negative": sorted(negative, key=lambda item: (-item["score"], item["ident"])),
            "unclassified": self._distinct_clusters(sorted(unclassified, key=lambda item: (-item["score"], item["ident"])), 10),
            "comparable_cases": comparable_cases,
            "family_margin": float(top - second),
        }

    def recommend(
        self,
        query: str,
        top_k: int = 50,
        component_override: str = "",
        fault_override: str = "",
        location_override: str = "",
    ) -> dict:
        query = str(query or "").strip()
        query_display = normalize_query_for_display(query)
        query_key = canonical_problem_key(query_display)
        query_components = find_components(query_display)
        query_fault = issue_family(query_display)
        query_faults = [query_fault] if query_fault else []
        query_locations = normalized_locations(query_display)
        override_fields = {
            "component": bool(str(component_override or "").strip()),
            "fault": bool(str(fault_override or "").strip()),
            "location": bool(str(location_override or "").strip()),
        }
        if override_fields["component"]:
            query_components = [canonical_component(component_override)]
        if override_fields["fault"]:
            corrected_fault = issue_family(fault_override) or canonical_problem_key(fault_override)
            query_faults = [corrected_fault] if corrected_fault else []
            query_fault = corrected_fault or None
        if override_fields["location"]:
            query_locations = normalized_locations(location_override)
        query_component = target_component(query_components)
        adapter_entities = (
            [{"type": "MAINT_ITEM", "text": value, "score": 1.0} for value in query_components]
            + [{"type": "FAULT", "text": value, "score": 1.0} for value in query_faults]
            + [{"type": "LOC", "text": value, "score": 1.0} for value in query_locations]
        )
        query_entities, query_relations, query_structure_source, query_structure_signature = self._query_structure(
            query_key, adapter_entities, query_component, any(override_fields.values())
        )
        hits, nearest_hits = self.search_operational(
            query_key,
            query_components,
            query_faults,
            query_locations,
            query_structure_signature,
            min(max(int(top_k), 5), 100),
        )
        evidence = self._aggregate(hits, query_components, query_faults, query_locations)
        nearest = [
            self._case(self.store.train.iloc[hit.idx], hit.score, hit.match_level)
            for hit in nearest_hits
        ]
        patterns = evidence["patterns"]
        primary = patterns[0] if patterns else None
        support = int(primary["support_clusters"]) if primary else 0
        top_score = nearest_hits[0].score if nearest_hits else 0.0
        second_score = nearest_hits[1].score if len(nearest_hits) > 1 else 0.0
        retrieval_margin = float(top_score - second_score)
        exact = any(self.docs[hit.idx] == query_key for hit in hits)
        near = any(SequenceMatcher(None, query_key, self.docs[hit.idx]).ratio() >= 0.87 for hit in hits[:10])
        rung = "A" if exact else "B" if near else "C" if hits else "D"
        same_position_support = int(primary["same_position_clusters"]) if primary else 0
        support_tier = (
            "strong" if same_position_support >= 3 or support >= 6
            else "moderate" if same_position_support >= 2 or support >= 3
            else "limited" if support >= 1
            else "nearest_cases_only"
        )
        badge = support_tier if primary else "abstain"
        component_label = query_component or "reported component"
        family_label = primary["family"] if primary else ""
        statement = primary["suggestion"] if primary else ""
        strategies = []
        for index, pattern in enumerate(patterns):
            category = "assessment" if pattern["family"] in {"Inspect", "Diagnose"} else "corrective"
            role = "primary" if index == 0 else "assessment_option" if category == "assessment" else "limited_alternative" if pattern["support_clusters"] == 1 else "supported_alternative"
            strategies.append({
                "family": pattern["family"],
                "action_target": pattern["action_target"],
                "sentence": pattern["suggestion"],
                "meaning": f"Recorded in {pattern['case_count']} comparable work order(s) across {pattern['support_clusters']} supporting independent event(s). Position is shown separately and is not silently pooled.",
                "support_clusters": pattern["support_clusters"],
                "matching_clusters": pattern["matching_clusters"],
                "same_position_clusters": pattern["same_position_clusters"],
                "other_position_clusters": pattern["other_position_clusters"],
                "position_not_recorded_clusters": pattern["position_not_recorded_clusters"],
                "query_position_unspecified_clusters": pattern["query_position_unspecified_clusters"],
                "full_structure_support_clusters": pattern["full_structure_support_clusters"],
                "case_count": pattern["case_count"],
                "same_position_cases": pattern["same_position_cases"],
                "other_position_cases": pattern["other_position_cases"],
                "position_not_recorded_cases": pattern["position_not_recorded_cases"],
                "query_position_unspecified_cases": pattern["query_position_unspecified_cases"],
                "other_positions": pattern["other_positions"],
                "share_of_comparable_cases": pattern["share_of_comparable_cases"],
                "outcome_positive": pattern["outcome_positive"],
                "outcome_negative": pattern["outcome_negative"],
                "outcome_unknown": pattern["outcome_unknown"],
                "examples": [
                    {
                        "ident": example["ident"],
                        "action": example["action"],
                        "outcome": example["outcome"],
                        "source_may_be_truncated": example["action_may_be_truncated"],
                    }
                    for example in pattern["examples"][:5]
                ],
                "is_primary": index == 0,
                "tier": "single_case" if pattern["support_clusters"] == 1 else "corroborated",
                "role": role,
                "category": category,
            })
        if strategies:
            summary_parts = [f"Primary recorded option: {strategies[0]['sentence']}"]
            for strategy in strategies[1:]:
                prefix = "Separately recorded assessment option" if strategy["category"] == "assessment" else "Limited one-cluster alternative" if strategy["tier"] == "single_case" else "Supported alternative"
                summary_parts.append(f"{prefix}: {strategy['sentence']}")
            action_set_summary = " ".join(summary_parts)
        else:
            action_set_summary = ""
        recommended = primary["examples"][:10] if primary else []
        # The frozen RQ5 calibrator was fitted to the frozen family-vote feature
        # distribution. It must not be presented as calibrated for this stricter
        # operational action-pattern layer.
        agreement = None
        if hits and (query_components or query_faults):
            top_row = self.store.train.iloc[hits[0].idx]
            component_match = int(target_component(list(top_row.components)) == query_component)
            fault_match = int(bool(set(query_faults) & set(top_row.faults)))
            if query_locations:
                location_match = int(set(query_locations) == set(top_row.locations))
                anchor_coverage = (component_match + fault_match + location_match) / 3.0
            else:
                anchor_coverage = (component_match + fault_match) / 2.0
        else:
            anchor_coverage = 0.0
        full_structure_clusters = len({
            str(self.store.train.iloc[hit.idx].cluster_id)
            for hit in hits if hit.match_level == "full entity-relation match"
        })
        relation_match_evaluated = query_structure_signature is not None
        structural_match_label = "Matching component-and-fault evidence" if hits else "No matching component-and-fault evidence"
        graph_coverage_note = (
            f"{full_structure_clusters} of {len(hits)} matching evidence cluster(s) also have an identical complete frozen entity-relation signature."
            if relation_match_evaluated
            else "Full relation equality is not claimed because this wording has no exact frozen TRAIN prediction; the deterministic adapter links the extracted component, fault and position anchors."
        )
        return {
            "query": query,
            "components": query_components,
            "faults": query_faults,
            "badge": badge,
            "lens": "problem_only_selective_history",
            "headline_action": family_label,
            "headline_reason": f"All displayed options match the same component and fault. The primary pattern has {same_position_support} event(s) at the reported position and {max(0, support - same_position_support)} at other or unrecorded positions." if primary else "No classified historical action matched the same component and fault. Broader nearest cases are shown without an action suggestion.",
            "support_clusters": support,
            "structured_sentence": statement,
            "action_set_summary": action_set_summary,
            "action_set": strategies,
            "action_set_sequence_supported": False,
            "action_set_note": "Corrective and assessment actions are presented as independently observed options. They are not joined into an ordered maintenance procedure because the source data does not annotate action sequence.",
            "strategies": strategies,
            "recommended_cases": recommended,
            "alternatives": strategies[1:],
            "nearest_cases": nearest,
            "negative_evidence": evidence["negative"][:10],
            "unclassified_action_evidence": evidence["unclassified"],
            "comparable_action_cases": evidence["comparable_cases"],
            "structure_source": query_structure_source,
            "entities": query_entities,
            "relations": query_relations,
            "family_evidence_margin": evidence["family_margin"],
            "retrieval_margin": retrieval_margin,
            "anchor_coverage": anchor_coverage,
            "abstain": not bool(primary),
            "evidence_family": family_label,
            "base_top_score": top_score,
            "evidence_tier": {"A": "exact canonical problem", "B": "near-duplicate with matching defect", "C": "same component and fault", "D": "broader nearest cases only"}[rung],
            "evidence_note": "Operational suggestions require the same component and fault. Position is reported as same, other, or not recorded; it is never pooled silently. Single-cluster actions remain visible.",
            "historical_agreement_probability": agreement,
            "calibration_source": "not_applied_to_operational_exact_anchor_layer",
            "reranker_used": True,
            "candidate_split": "train",
            "model_components": query_components,
            "model_faults": query_faults,
            "derived_components": query_components,
            "derived_faults": query_faults,
            "target_location": " / ".join(query_locations),
            "partial_structure_warning": "Complete entity-relation equality is claimed only for an exact frozen TRAIN prediction. For unseen wording, deterministic schema links are displayed and position is treated as a disclosed evidence stratum rather than a hard gate.",
            "model_input": query_key,
            "input_adapter": "selective_canonical_problem_key_with_engineer_anchor_override" if any(override_fields.values()) else "selective_canonical_problem_key",
            "input_adapted": query_key != canonical_problem_key(query),
            "normalized_interpretation": query_display,
            "normalization_model_input": query,
            "normalization_method": "protected_rules_then_canonical_key",
            "normalization_warning": "Engineer-supplied anchor corrections were applied and are explicitly disclosed; the original problem text and frozen evidence remain unchanged." if any(override_fields.values()) else "Numbers and directional anchors are preserved; no neural rewrite is accepted in the default hosted profile.",
            "normalization_model": "none_required_frozen_artifact_profile",
            "semantic_branch_used": False,
            "semantic_status": query_structure_source,
            "semantic_warning": "No live neural model is required: exact TRAIN text can reuse its frozen Selective SpERT graph; unseen wording uses the deterministic protected-token adapter.",
            "semantic_entities": query_entities,
            "semantic_relations": query_relations,
            "semantic_components": query_components,
            "semantic_faults": query_faults,
            "semantic_locations": query_locations,
            "rq4_entities": query_entities,
            "rq4_relations": query_relations,
            "rq4_components": query_components,
            "rq4_faults": query_faults,
            "rq4_structure_source": f"frozen_selective_canonical_bm25_plus_{query_structure_source}",
            "rq4_live_validated": relation_match_evaluated,
            "compound_detected": False,
            "decomposition_source": "disabled_no_procedure_synthesis",
            "subproblems": [],
            "operational_match_policy": "same target component + same fault; position retained as a ranking preference and disclosed evidence stratum",
            "matching_signature": {
                "component": query_component,
                "fault": query_fault or "",
                "locations": query_locations,
            },
            "query_position_specified": bool(query_locations),
            "exact_match_clusters": len(hits),
            "same_position_match_clusters": len({str(self.store.train.iloc[hit.idx].cluster_id) for hit in hits if query_locations and ("same position" in hit.match_level or hit.match_level == "full entity-relation match")}),
            "other_position_match_clusters": len({str(self.store.train.iloc[hit.idx].cluster_id) for hit in hits if "other position" in hit.match_level}),
            "query_position_unspecified_match_clusters": len({str(self.store.train.iloc[hit.idx].cluster_id) for hit in hits}) if not query_locations else 0,
            "full_structure_match_clusters": full_structure_clusters,
            "relation_match_evaluated": relation_match_evaluated,
            "structural_match_label": structural_match_label,
            "graph_coverage_note": graph_coverage_note,
            "query_structure_source": query_structure_source,
            "anchor_overrides_applied": override_fields,
            "manual_anchor_override": any(override_fields.values()),
        }
