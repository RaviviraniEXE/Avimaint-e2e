from __future__ import annotations

import json
import hashlib
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from .calibration import AgreementCalibrator
from .data_store import DataStore
from .retrieval import SelectiveRetriever
from .settings import settings
from .views import case_lookup, insights, job_card, knowledge_graph, overview, recurring_rows


@asynccontextmanager
async def lifespan(_app: FastAPI):
    runtime()
    yield


app = FastAPI(
    title="AviMaint-DSS Selective API",
    version=settings.api_version,
    description="Frozen Selective-ByT5 historical retrieval and planning evidence.",
    lifespan=lifespan,
)


class DiagnoseRequest(BaseModel):
    query: str = Field(min_length=1, max_length=5000)
    top_k: int = Field(default=50, ge=5, le=100)
    component_override: str = Field(default="", max_length=200)
    fault_override: str = Field(default="", max_length=200)
    location_override: str = Field(default="", max_length=200)


class JobCardRequest(BaseModel):
    cluster_id: str = Field(min_length=1, max_length=100)


class FeedbackRequest(BaseModel):
    rating: Literal["useful", "needs_review"]
    query: str = Field(min_length=1, max_length=5000)
    badge: str = Field(default="", max_length=50)
    headline_action: str = Field(default="", max_length=200)
    support_clusters: int = Field(default=0, ge=0, le=10000)


FEEDBACK_PATH = settings.feedback_path
_FEEDBACK_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def runtime() -> tuple[DataStore, AgreementCalibrator, SelectiveRetriever]:
    store = DataStore(settings)
    calibrator = AgreementCalibrator(settings.data_dir / "research" / "RQ5_PLANNING_SUPPORT.json")
    return store, calibrator, SelectiveRetriever(store, settings, calibrator)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/v1/health")
def health():
    store, calibrator, _retriever = runtime()
    frontend_ready = (settings.frontend_dist / "index.html").is_file()
    return {
        "status": "ready" if frontend_ready else "degraded",
        "api_version": settings.api_version,
        "rq4_base": settings.retrieval_mode,
        "candidate_split": settings.candidate_split,
        "critical_ready": frontend_ready,
        "phase2_compound_decomposition": False,
        "phase3_limited_evidence": True,
        "raw_spert": {"ready": True, "metadata": {"mode": "frozen_selective_predictions", "records": len(store.df)}},
        "normalization": {"ready": True, "metadata": {"mode": "protected_rules_then_canonical_key", "neural_model_required": False}},
        "semantic_spert": {"ready": True, "metadata": {"mode": "precomputed_corpus_predictions", "live_query_model": False}},
        "rq5_calibrator": {"ready": True, "status": "frozen_json_parameters", "metadata": {"ece": calibrator.ece, "brier": calibrator.brier}},
        "frontend": {"ready": frontend_ready, "version": "8.3.2", "expected_version": "8.3.2", "mode": "fastapi_static", "url": "/"},
        "operational_matching": {
            "ready": True,
            "policy": "same target component + same fault; position is a disclosed ranking stratum",
            "action_ranking": "distinct supporting evidence-cluster frequency, then same-position support",
            "single_support": "visible as limited evidence",
            "action_presentation": "target-specific non-sequential action alternatives with same/other-position counts",
            "full_graph_claim": "only for exact frozen TRAIN text with equal entity-relation signature",
        },
        "runtime_model_lock": {"profile": settings.runtime_profile, "neural_models_loaded": 0, "optional_neural_models": 2},
    }


@app.post("/api/v1/diagnose")
def diagnose(request: DiagnoseRequest):
    _store, _calibrator, retriever = runtime()
    return {
        "result": retriever.recommend(
            request.query,
            request.top_k,
            request.component_override,
            request.fault_override,
            request.location_override,
        ),
        "meta": {
            "rq4_base": settings.retrieval_mode,
            "candidate_split": settings.candidate_split,
            "reranker_role": "operational_component_fault_filter_with_position_preference_after_frozen_bm25",
            "operational_layer": "same_component_fault_target_specific_action_patterns",
            "rq5_meaning": "historical_action_family_agreement",
            "technical_correctness_probability": False,
        },
    }


@app.get("/api/v1/overview")
def overview_route():
    return overview(runtime()[0])


@app.post("/api/v1/feedback")
def feedback_route(request: FeedbackRequest):
    record = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "api_version": settings.api_version,
        "rating": request.rating,
        "query_sha256": hashlib.sha256(request.query.strip().encode("utf-8")).hexdigest(),
        "badge": request.badge,
        "headline_action": request.headline_action,
        "support_clusters": request.support_clusters,
        "meaning": "user-rated usefulness of the displayed historical evidence; not technical correctness",
    }
    with _FEEDBACK_LOCK:
        FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with FEEDBACK_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return {"status": "recorded", "query_stored": False, "technical_correctness_label": False}


@app.get("/api/v1/insights")
def insights_route(
    component: str = Query(default="", max_length=300),
    fault: str = Query(default="", max_length=300),
):
    return insights(runtime()[0], component, fault)


@app.get("/api/v1/case/{ident}")
def case_route(ident: str):
    result = case_lookup(runtime()[0], ident)
    if result is None:
        raise HTTPException(status_code=404, detail="Work order not found in the frozen Selective corpus")
    return {
        "case": result,
        "warning": "This is a historical source record, not an approved maintenance instruction.",
    }


@app.get("/api/v1/knowledge-graph")
def graph_route(
    top_components: int = Query(default=10, ge=5, le=20),
    top_faults: int = Query(default=8, ge=4, le=15),
    min_edge: int = Query(default=3, ge=1, le=50),
    focus_component: str = Query(default="", max_length=300),
):
    return knowledge_graph(runtime()[0], top_components, top_faults, min_edge, focus_component)


@app.get("/api/v1/planning/recurring")
def recurring_route(min_support: int = Query(default=5, ge=1, le=1000), limit: int = Query(default=40, ge=1, le=200)):
    return {
        "items": recurring_rows(runtime()[0].df, min_support, limit),
        "min_support": min_support,
        "note": "Presentation groups collapse harmless wording variants without changing research evidence clusters.",
    }


@app.post("/api/v1/planning/job-card")
def job_card_route(request: JobCardRequest):
    card = job_card(runtime()[0], request.cluster_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Historical presentation group not found")
    return {
        "card": card,
        "cluster_id": request.cluster_id,
        "warning": "Every line is copied from a recorded normalized action. Truncated source text is flagged and must not be completed by inference.",
    }


@app.get("/api/v1/evaluation")
def evaluation():
    root = settings.data_dir / "research"
    rq4 = _json(root / "RQ4_FINAL_TEST.json")
    rq4["selected_mode_metrics"] = rq4.get("selected_configuration_metrics", {})
    manual = {
        "phase_a": {
            "problem_relevance_hit_at_1": 0.92,
            "problem_relevance_hit_at_3": 0.95,
            "problem_relevance_hit_at_5": 0.97,
            "mean_ndcg_problem_relevance_at_5": 0.9052829349145042,
            "reviewed_queries": 100,
            "reviewed_pairs": 500,
        },
        "phase_b": {
            "problem_relevant_pairs_revealed": 433,
            "applicable_or_partial_rate_among_problem_relevant_pairs": 0.9884526558891455,
            "clearly_applicable_rate_among_problem_relevant_pairs": 0.789838337182448,
            "usable_historical_action_evidence_hit_at_1": 0.92,
            "usable_historical_action_evidence_hit_at_3": 0.95,
            "usable_historical_action_evidence_hit_at_5": 0.97,
        },
    }
    return {
        "frozen": {
            "rq4": rq4,
            "rq5": _json(root / "RQ5_PLANNING_SUPPORT.json"),
            "manual": manual,
            "lock": _json(root / "FINAL_TEST_LOCK.json"),
        },
        "warning": "These immutable values describe the final Selective protocol; operational presentation grouping does not rewrite them.",
    }


def _index():
    path = settings.frontend_dist / "index.html"
    if not path.is_file():
        return HTMLResponse("<h1>Frontend not built</h1>", status_code=503)
    response = FileResponse(path)
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/", include_in_schema=False)
def index():
    return _index()


@app.get("/{full_path:path}", include_in_schema=False)
def static_files(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API route not found")
    root = settings.frontend_dist.resolve()
    target = (settings.frontend_dist / full_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc
    if target.is_file():
        response = FileResponse(target)
        if full_path.startswith("assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response
    return _index()
