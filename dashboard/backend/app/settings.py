from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    data_dir: Path = ROOT / "data"
    frontend_dist: Path = ROOT / "frontend" / "dist"
    model_dir: Path = ROOT / "models"
    runtime_profile: str = os.getenv("AVIMAINT_RUNTIME_PROFILE", "frozen_artifacts")
    api_version: str = "8.3.2"
    feedback_path: Path = Path(os.getenv("AVIMAINT_FEEDBACK_PATH", str(ROOT / "runtime" / "feedback.jsonl")))
    representation: str = "selective_byt5"
    retrieval_mode: str = "selective_canonical_bm25"
    candidate_split: str = "train"
    selected_tau: float = 0.15
    retrieval_depth: int = 50


settings = Settings()
