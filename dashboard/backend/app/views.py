from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass

import pandas as pd

from .data_store import DataStore
from .terminology import defect_component, display_location, looks_truncated


def _explode(frame: pd.DataFrame, column: str) -> Counter:
    return Counter(
        defect_component(value) if column == "components" else value
        for values in frame[column]
        for value in values
        if value and value != "(unspecified)"
    )


def _frequency(counter: Counter, key: str, limit: int = 20) -> list[dict]:
    total = sum(counter.values()) or 1
    running = 0
    rows = []
    for value, count in counter.most_common(limit):
        running += count
        rows.append({key: value, "work_orders": int(count), "share_pct": round(count / total * 100, 1), "cumulative_pct": round(running / total * 100, 1)})
    return rows


def _representative(sub: pd.DataFrame) -> str:
    options = sorted(set(sub["problem"].astype(str)), key=lambda value: (looks_truncated(value), len(value), value))
    return options[0] if options else ""


def recurring_rows(frame: pd.DataFrame, min_support: int = 1, limit: int = 40) -> list[dict]:
    rows = []
    for group_id, sub in frame.groupby("display_group_id"):
        if len(sub) < min_support:
            continue
        components = Counter(value for value in sub.component if value != "(unspecified)")
        faults = Counter(value for value in sub.fault if value != "(unspecified)")
        actions = Counter(value for value in sub.action_family if value != "Other")
        positive = int((sub.outcome == "positive").sum())
        negative = int(sub.outcome.isin(["negative", "mixed"]).sum())
        rows.append({
            "cluster_id": str(group_id),
            "problem": _representative(sub),
            "component": components.most_common(1)[0][0] if components else "",
            "fault": faults.most_common(1)[0][0] if faults else "",
            "work_orders": int(len(sub)),
            "top_action": actions.most_common(1)[0][0] if actions else "",
            "dominant_action": actions.most_common(1)[0][0] if actions else "",
            "positive_outcomes": positive,
            "negative_outcomes": negative,
            "outcome_unknown": int(len(sub) - positive - negative),
            "research_clusters": int(sub.cluster_id.nunique()),
        })
    return sorted(rows, key=lambda row: (-row["work_orders"], row["problem"]))[:limit]


def defect_register_rows(frame: pd.DataFrame, min_support: int = 5) -> list[dict]:
    """Build planner-facing defect rows without changing research clusters.

    The grouping is intentionally based on reviewed component/fault labels;
    position is retained as a distribution instead of creating duplicate rows.
    """
    prepared = frame.copy()
    prepared["defect_component"] = prepared["component"].map(defect_component)
    prepared = prepared[
        (prepared["defect_component"] != "(unspecified)")
        & (prepared["fault"] != "(unspecified)")
    ]
    rows: list[dict] = []
    for (component, fault), sub in prepared.groupby(["defect_component", "fault"]):
        if len(sub) < min_support:
            continue
        actions = Counter(str(value) for value in sub.action_family)
        dominant_action, dominant_count = actions.most_common(1)[0] if actions else ("", 0)
        positive = int((sub.outcome == "positive").sum())
        negative = int(sub.outcome.isin(["negative", "mixed"]).sum())
        recorded = positive + negative
        position_counts: Counter = Counter()
        for values in sub.locations:
            label = " + ".join(display_location(value) for value in values) if values else "not recorded"
            position_counts[label] += 1
        rows.append({
            "cluster_id": f"DEFECT::{component}::{fault}",
            "problem": f"{component} → {fault}",
            "component": component,
            "fault": fault,
            "work_orders": int(len(sub)),
            "dominant_action": dominant_action,
            "dominant_action_share": dominant_count / len(sub),
            "distinct_families": int(len([family for family in actions if family != "Other"])),
            "other_dominant": dominant_action == "Other",
            "positive_outcomes": positive,
            "negative_outcomes": negative,
            "outcome_unknown": int(len(sub) - recorded),
            "recorded_outcome_rate": recorded / len(sub),
            "positive_rate_among_recorded": positive / recorded if recorded else None,
            "research_clusters": int(sub.cluster_id.nunique()),
            "positions": [
                {"position": position, "work_orders": int(count)}
                for position, count in position_counts.most_common(8)
            ],
        })
    return rows


def outcome_rows(frame: pd.DataFrame) -> list[dict]:
    counts = frame.outcome.value_counts()
    return [{"outcome": label, "work_orders": int(counts.get(label, 0))} for label in ("positive", "unknown", "negative", "mixed")]


def overview(store: DataStore) -> dict:
    frame = store.df
    support = frame.groupby("display_group_id").size()
    defects = defect_register_rows(frame, 2)
    frequent_defects = sorted(defects, key=lambda row: (-row["work_orders"], row["problem"]))
    multi_family_clusters = 0
    repeated_clusters = 0
    for _cluster, sub in frame.groupby("cluster_id"):
        if len(sub) < 2:
            continue
        repeated_clusters += 1
        if sub[sub.action_family != "Other"].action_family.nunique() > 1:
            multi_family_clusters += 1
    return {
        "kpis": {
            "work_orders": int(len(frame)),
            "unique_problems": int(frame.display_key.nunique()),
            "problem_clusters": int(frame.cluster_id.nunique()),
            "components_tracked": len(_explode(frame, "components")),
            "action_families": int(frame[frame.action_family != "Other"].action_family.nunique()),
            "recurring_faults": int((support >= 5).sum()),
            "recorded_outcomes_pct": round(float((frame.outcome != "unknown").mean()) * 100, 1),
            "spert_backed": True,
            "most_recurring_defect": frequent_defects[0]["problem"] if frequent_defects else "Not available",
            "most_recurring_defect_orders": frequent_defects[0]["work_orders"] if frequent_defects else 0,
            "multi_action_clusters": multi_family_clusters,
            "repeated_clusters": repeated_clusters,
            "multi_action_cluster_pct": round(multi_family_clusters / repeated_clusters * 100, 1) if repeated_clusters else 0.0,
            "single_record_defects": int(sum(row["work_orders"] == 1 for row in defect_register_rows(frame, 1))),
        },
        "top_recurring": frequent_defects[:12],
        "component_frequency": _frequency(_explode(frame, "components"), "component", 15),
        "fault_frequency": _frequency(_explode(frame, "faults"), "fault", 15),
        "action_frequency": _frequency(Counter(frame[frame.action_family != "Other"].action_family), "action_family", 15),
        "outcome_mix": outcome_rows(frame),
        "note": "All 6,169 frozen Selective records are used for descriptive views. Diagnose retrieves TRAIN only.",
    }


def insights(store: DataStore, component: str = "", fault: str = "") -> dict:
    frame = store.df
    components = _explode(frame, "components")
    faults = _explode(frame, "faults")
    component_names = [name for name, _count in components.most_common(100)]
    selected = component if component in component_names else ""
    fault_names = [name for name, _count in faults.most_common()]
    selected_fault = fault if fault in fault_names else ""
    filtered = frame
    if selected:
        filtered = filtered[filtered.components.map(lambda values: selected in {defect_component(value) for value in values})]
    if selected_fault:
        filtered = filtered[filtered.faults.map(lambda values: selected_fault in set(values))]
    top_components = [name for name, _count in components.most_common(12)]
    top_faults = [name for name, _count in faults.most_common(12)]
    matrix = [[0 for _ in top_faults] for _ in top_components]
    component_index = {name: index for index, name in enumerate(top_components)}
    fault_index = {name: index for index, name in enumerate(top_faults)}
    for row in frame.itertuples(index=False):
        for comp in {defect_component(value) for value in row.components}:
            if comp not in component_index:
                continue
            for fault in set(row.faults):
                if fault in fault_index:
                    matrix[component_index[comp]][fault_index[fault]] += 1
    return {
        "recurring": defect_register_rows(frame, 5),
        "components": _frequency(components, "component", 20),
        "faults": _frequency(faults, "fault", 20),
        "actions": _frequency(Counter(frame[frame.action_family != "Other"].action_family), "action_family", 20),
        "outcomes": outcome_rows(frame),
        "matrix": {"components": top_components, "faults": top_faults, "values": matrix},
        "component_options": component_names,
        "selected_component": selected,
        "selected_fault": selected_fault,
        "component_actions": _frequency(Counter(filtered[filtered.action_family != "Other"].action_family), "action_family", 12),
        "note": "The chronic-defect register groups reviewed presentation aliases by component and fault; position remains visible as a distribution. Frozen evidence clusters and retrieval results are unchanged. Counts are not failure rates.",
        "reviewed_aliases": [
            {"source": "intake", "display_as": "intake gasket"},
            {"source": "rocker cover", "display_as": "rocker cover gasket"},
        ],
    }


def knowledge_graph(store: DataStore, top_components: int, top_faults: int, min_edge: int, focus_component: str) -> dict:
    frame = store.df
    component_counts = _explode(frame, "components")
    fault_counts = _explode(frame, "faults")
    focus = next((name for name in component_counts if name.casefold() == focus_component.casefold()), "") if focus_component else ""
    selected_components = {focus} if focus else {name for name, _ in component_counts.most_common(top_components)}
    focus_frame = frame[frame.components.map(lambda values: focus in {defect_component(value) for value in values})] if focus else frame
    selected_faults = {name for name, _ in _explode(focus_frame, "faults").most_common(max(top_faults, 12) if focus else top_faults)}
    edge_floor = 1 if focus else min_edge
    cf = Counter(); fa = Counter(); af = Counter()
    for row in frame.itertuples(index=False):
        comps = {defect_component(value) for value in row.components} & selected_components
        faults = set(row.faults) & selected_faults
        for comp in comps:
            for fault in faults:
                cf[(comp, fault)] += 1
        if row.action_family != "Other" and (not focus or focus in {defect_component(value) for value in row.components}):
            af[row.action_family] += 1
            for fault in faults:
                fa[(fault, row.action_family)] += 1
    nodes = {}; edges = []; used_faults = set()
    for (comp, fault), count in cf.items():
        if count < edge_floor:
            continue
        cid, fid = f"component:{comp}", f"fault:{fault}"
        nodes[cid] = {"id": cid, "label": comp, "kind": "component", "count": int(component_counts[comp]), "focused": comp == focus}
        fault_node_count = cf[(comp, fault)] if focus else fault_counts[fault]
        nodes[fid] = {"id": fid, "label": fault, "kind": "fault", "count": int(fault_node_count), "focused": False}
        edges.append({"source": cid, "target": fid, "kind": "component_fault", "count": int(count)})
        used_faults.add(fault)
    for (fault, family), count in fa.items():
        if count < edge_floor or fault not in used_faults:
            continue
        fid, aid = f"fault:{fault}", f"action:{family}"
        nodes[aid] = {"id": aid, "label": family, "kind": "action", "count": int(af[family]), "focused": False}
        edges.append({"source": fid, "target": aid, "kind": "fault_action", "count": int(count)})
    order = {"component": 0, "fault": 1, "action": 2}
    return {
        "nodes": sorted(nodes.values(), key=lambda node: (order[node["kind"]], -node["count"], node["label"])),
        "edges": sorted(edges, key=lambda edge: (-edge["count"], edge["source"], edge["target"])),
        "focus_component": focus,
        "component_options": [name for name, _ in component_counts.most_common(100)],
        "parameters": {"top_components": top_components, "top_faults": top_faults, "min_edge": edge_floor},
        "scope": {
            "label": f"all records containing problem component: {focus}" if focus else "all 6,169 corpus records",
            "records": int(len(focus_frame)),
            "action_basis": "recorded action family among records in this problem-side scope",
        },
        "note": "Focused node counts are recomputed inside the selected problem-component scope. Action nodes are recorded action families, not action targets or causal relationships.",
    }


def job_card(store: DataStore, display_group_id: str) -> dict | None:
    sub = store.df[store.df.display_group_id == display_group_id]
    if sub.empty:
        return None
    components = Counter(value for value in sub.component if value != "(unspecified)")
    faults = Counter(value for value in sub.fault if value != "(unspecified)")
    eligible = sub[(~sub.outcome.isin(["negative", "mixed"])) & (sub.action_family != "Other")]
    steps = []
    seen = set()
    for row in eligible.sort_values(["action_family", "ident"]).itertuples(index=False):
        key = " ".join(str(row.action).lower().split())
        if not key or key in seen:
            continue
        seen.add(key)
        steps.append({"text": str(row.action), "source_idents": [str(row.ident)], "source_may_be_truncated": looks_truncated(str(row.action))})
        if len(steps) >= 8:
            break
    actions = Counter(eligible.action_family)
    positive = int((sub.outcome == "positive").sum())
    negative = int(sub.outcome.isin(["negative", "mixed"]).sum())
    return {
        "title": _representative(sub),
        "component": components.most_common(1)[0][0] if components else "",
        "fault": faults.most_common(1)[0][0] if faults else "",
        "work_orders": int(len(sub)),
        "problem_groups": int(sub.cluster_id.nunique()),
        "dominant_action": actions.most_common(1)[0][0] if actions else "",
        "steps": steps,
        "references": [],
        "outcome_positive": positive,
        "outcome_negative": negative,
        "outcome_unknown": int(len(sub) - positive - negative),
        "source_idents": sub.ident.astype(str).tolist(),
    }


def case_lookup(store: DataStore, ident: str) -> dict | None:
    sub = store.df[store.df.ident == str(ident).strip()]
    if sub.empty:
        return None
    row = sub.iloc[0]
    return {
        "ident": str(row.ident),
        "problem": str(row.problem),
        "problem_raw": str(row.problem_raw),
        "action": str(row.action),
        "action_raw": str(row.action_raw),
        "action_family": str(row.action_family),
        "action_kind": "assessment documented" if str(row.action_family) in {"Inspect", "Diagnose"} else "corrective action documented" if str(row.action_family) != "Other" else "unclassified action text",
        "outcome": str(row.outcome),
        "outcome_label": "resolved outcome recorded" if str(row.outcome) == "positive" else "did not resolve / mixed outcome recorded" if str(row.outcome) in {"negative", "mixed"} else "post-action outcome not recorded",
        "component": str(row.component),
        "fault": str(row.fault),
        "locations": [display_location(value) for value in row.locations],
        "entities": list(row.problem_entities),
        "relations": list(row.problem_relations),
        "evidence_cluster": str(row.cluster_id),
        "split": str(row.frozen_split),
        "problem_may_be_truncated": looks_truncated(str(row.problem)),
        "action_may_be_truncated": looks_truncated(str(row.action)),
    }
