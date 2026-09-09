from __future__ import annotations

import json

from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app, runtime
from app.settings import settings
from app.terminology import canonical_problem_key, defect_component, display_problem_key, find_components, merge_components, normalized_locations, target_component
from app.views import job_card, recurring_rows


def test_number_and_alias_keys_are_symmetric():
    assert canonical_problem_key("#2 INTAKES LEAKING") == canonical_problem_key("NUMBER TWO INTAKE LEAKING")
    assert display_problem_key("#2 INTAKE IS LEAKING") == display_problem_key("#2 INTAKE LEAKING")


def test_distinct_component_granularity_is_preserved():
    assert find_components("NUMBER 2 INTAKE GASKET LEAKING") == ["intake gasket"]
    assert find_components("NUMBER 2 INTAKE LEAKING") == ["intake"]


def test_component_plurals_collapse_without_merging_distinct_parts():
    assert find_components("ROCKER COVER GASKETS LEAKING") == ["rocker cover gasket"]
    assert merge_components(
        "ROCKER COVER GASKETS LEAKING",
        ["rocker cover gaskets", "rocker covers", "gasket"],
    ) == ["rocker cover gasket"]
    assert normalized_locations("#2 INTAKE LEAKING") == normalized_locations("NUMBER TWO INTAKE LEAKING") == ["num_2"]


def test_frozen_identity_and_prior_distribution():
    store, _calibrator, _retriever = runtime()
    assert len(store.df) == 6169
    assert len(store.train) == 4319
    assert abs(sum(store.family_priors.values()) - 1.0) < 1e-12
    assert 0.63 < store.family_priors["Replace"] < 0.65


def test_api_and_single_support_visibility():
    client = TestClient(app)
    assert client.get("/api/v1/health").status_code == 200
    response = client.post("/api/v1/diagnose", json={"query": "#2 intake leaking", "top_k": 50})
    assert response.status_code == 200
    payload = response.json()["result"]
    assert payload["candidate_split"] == "train"
    assert payload["strategies"]
    assert any(item["tier"] == "single_case" for item in payload["strategies"])
    assert payload["structured_sentence"] == "Replace the number 2 intake gasket."
    assert payload["same_position_match_clusters"] > 0
    assert payload["other_position_match_clusters"] > payload["same_position_match_clusters"]
    assert payload["action_set"][0]["same_position_clusters"] > 0
    assert payload["action_set"][0]["other_position_clusters"] > 0
    assert any(item["sentence"] == "Repair the number 2 intake gasket." for item in payload["action_set"])
    assert any(item["action_target"] != "intake gasket" for item in payload["action_set"])
    assert payload["action_set"][0]["role"] == "primary"
    repair = next(item for item in payload["action_set"] if item["family"] == "Repair")
    assert repair["role"] == "limited_alternative"
    assert payload["action_set_sequence_supported"] is False
    assert payload["action_set_summary"].startswith("Primary recorded option: Replace the number 2 intake gasket.")
    assert payload["matching_signature"] == {"component": "intake", "fault": "leak", "locations": ["num_2"]}
    assert payload["relation_match_evaluated"] is False
    assert {item["type"] for item in payload["relations"]} == {"ISSUE_ON_ITEM", "HAS_LOCATION"}
    assert all(item["source"] == "deterministic_schema_adapter" for item in payload["relations"])
    assert payload["full_structure_match_clusters"] == 0
    assert payload["structural_match_label"] == "Matching component-and-fault evidence"
    assert payload["historical_agreement_probability"] is None
    assert all(item["match_level"] in {"same component and fault · same position", "same component and fault · other position", "full entity-relation match"} for item in payload["recommended_cases"])
    assert payload["action_set"][0]["outcome_unknown"] > payload["action_set"][0]["outcome_positive"]
    assert all(item["outcome_label"] != "successful" for item in payload["recommended_cases"])
    assert all("action" in item for item in payload["nearest_cases"])
    assert len({item["cluster_id"] for item in payload["recommended_cases"]}) == len(payload["recommended_cases"])


def test_full_graph_claim_requires_an_exact_frozen_train_problem():
    client = TestClient(app)
    response = client.post(
        "/api/v1/diagnose",
        json={"query": "NUMBER TWO CYLINDER INTAKE LEAKING.", "top_k": 50},
    )
    assert response.status_code == 200
    payload = response.json()["result"]
    assert payload["query_structure_source"] == "frozen_train_exact_text_prediction"
    assert payload["relation_match_evaluated"] is True
    assert payload["full_structure_match_clusters"] >= 1
    assert any(item["full_structure_support_clusters"] >= 1 for item in payload["action_set"])
    assert payload["entities"]
    assert payload["relations"]
    assert any(item["match_level"] == "full entity-relation match" for item in payload["nearest_cases"])


def test_position_is_a_disclosed_preference_but_component_and_fault_remain_gates():
    store, _calibrator, retriever = runtime()
    query = canonical_problem_key("Number 2 intake leaking")
    hits, _nearest = retriever.search_operational(query, ["intake"], ["leak"], ["num_2"], None, 50)
    assert hits
    assert any("other position" in hit.match_level for hit in hits)
    for hit in hits:
        row = store.train.iloc[hit.idx]
        assert target_component(list(row.components)) == "intake"
        assert "leak" in row.faults


def test_target_component_and_reviewed_descriptive_aliases():
    assert target_component(["cylinder", "intake gasket"]) == "intake gasket"
    assert defect_component("intake") == "intake gasket"
    assert defect_component("rocker cover") == "rocker cover gasket"
    assert defect_component("gasket") == "gasket"
    store, _calibrator, _retriever = runtime()
    low_compression = store.df[
        store.df.problem.str.contains("LOW COMPRESSION", case=False)
        & ~store.df.problem.str.contains("LEAK", case=False)
    ]
    assert not low_compression.empty
    assert set(low_compression.fault) == {"low compression"}


def test_planning_uses_the_specific_target_component():
    store, _calibrator, _retriever = runtime()
    matching = store.df[store.df.problem.str.contains("CYLINDER NUMBER TWO INTAKE GASKET LEAKING", case=False, regex=False)]
    assert not matching.empty
    source = matching.iloc[0]
    assert source.component == "intake gasket"
    recurring = {row["cluster_id"]: row for row in recurring_rows(store.df, 1, 10000)}
    assert recurring[str(source.display_group_id)]["component"] == "intake gasket"
    assert job_card(store, str(source.display_group_id))["component"] == "intake gasket"


def test_engineer_anchor_override_is_disclosed_and_uses_adapter():
    client = TestClient(app)
    response = client.post("/api/v1/diagnose", json={
        "query": "NUMBER TWO CYLINDER INTAKE LEAKING.",
        "component_override": "intake gasket",
        "fault_override": "leak",
        "location_override": "number two",
    })
    assert response.status_code == 200
    payload = response.json()["result"]
    assert payload["manual_anchor_override"] is True
    assert payload["matching_signature"] == {"component": "intake gasket", "fault": "leak", "locations": ["num_2"]}
    assert payload["query_structure_source"] == "deterministic_schema_adapter_user_corrected"
    assert payload["relation_match_evaluated"] is False


def test_missing_query_position_is_not_presented_as_same_position():
    payload = TestClient(app).post("/api/v1/diagnose", json={"query": "Engine runs rough"}).json()["result"]
    assert payload["query_position_specified"] is False
    assert payload["same_position_match_clusters"] == 0
    assert payload["other_position_match_clusters"] == 0
    assert payload["query_position_unspecified_match_clusters"] > 0
    assert payload["action_set"][0]["query_position_unspecified_cases"] > 0


def test_feedback_hashes_query_and_is_not_a_correctness_label(tmp_path, monkeypatch):
    path = tmp_path / "feedback.jsonl"
    monkeypatch.setattr(main_module, "FEEDBACK_PATH", path)
    query = "Number two intake leaking"
    response = TestClient(app).post("/api/v1/feedback", json={
        "rating": "useful",
        "query": query,
        "badge": "strong",
        "headline_action": "Replace",
        "support_clusters": 6,
    })
    assert response.status_code == 200
    assert response.json() == {"status": "recorded", "query_stored": False, "technical_correctness_label": False}
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["rating"] == "useful"
    assert record["meaning"].endswith("not technical correctness")
    assert query not in path.read_text(encoding="utf-8")


def test_every_dashboard_endpoint_uses_the_same_release():
    client = TestClient(app)
    overview = client.get("/api/v1/overview")
    assert overview.status_code == 200
    assert overview.json()["kpis"]["work_orders"] == 6169
    assert overview.json()["kpis"]["multi_action_clusters"] == 242
    assert "→" in overview.json()["top_recurring"][0]["problem"]
    assert " — " not in overview.json()["top_recurring"][0]["problem"]
    insights = client.get("/api/v1/insights")
    assert insights.status_code == 200
    component_names = {item["component"] for item in insights.json()["components"]}
    assert "rocker covers" not in component_names
    assert "rocker cover gaskets" not in component_names
    assert "rocker cover" not in component_names
    selected = client.get("/api/v1/insights?component=intake%20gasket&fault=leak").json()
    assert selected["selected_component"] == "intake gasket"
    assert selected["selected_fault"] == "leak"
    assert selected["component_actions"]
    graph = client.get("/api/v1/knowledge-graph")
    assert graph.status_code == 200
    focused = client.get("/api/v1/knowledge-graph?focus_component=intake%20gasket&min_edge=1").json()
    assert focused["scope"]["label"].endswith("intake gasket")
    leak_node = next(node for node in focused["nodes"] if node["id"] == "fault:leak")
    leak_edge = next(edge for edge in focused["edges"] if edge["source"] == "component:intake gasket" and edge["target"] == "fault:leak")
    assert leak_node["count"] == leak_edge["count"]
    assert leak_node["count"] < 3116
    recurring = client.get("/api/v1/planning/recurring?min_support=1&limit=3")
    assert recurring.status_code == 200
    group_id = recurring.json()["items"][0]["cluster_id"]
    card = client.post("/api/v1/planning/job-card", json={"cluster_id": group_id})
    assert card.status_code == 200
    evaluation = client.get("/api/v1/evaluation")
    assert evaluation.status_code == 200
    assert evaluation.json()["frozen"]["rq4"]["selected_tau"] == 0.15
    case = client.get("/api/v1/case/100742")
    assert case.status_code == 200
    assert case.json()["case"]["outcome_label"] in {
        "resolved outcome recorded",
        "did not resolve / mixed outcome recorded",
        "post-action outcome not recorded",
    }
    expected_static_status = 200 if (settings.frontend_dist / "index.html").is_file() else 503
    assert client.get("/").status_code == expected_static_status
    assert client.get("/diagnose").status_code == expected_static_status
