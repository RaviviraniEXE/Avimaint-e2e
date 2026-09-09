from __future__ import annotations

import json
import math
from pathlib import Path


class AgreementCalibrator:
    def __init__(self, artifact: Path):
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        self.mean = [float(value) for value in payload["scaler_mean"]]
        self.scale = [float(value) for value in payload["scaler_scale"]]
        self.coefficients = [float(value) for value in payload["logistic_coefficients"]]
        self.intercept = float(payload["logistic_intercept"])
        self.ece = float(payload["ece_10_bins"])
        self.brier = float(payload["brier_score"])

    def predict(self, top_score: float, margin: float, support_clusters: int) -> float:
        features = [float(top_score), float(margin), float(support_clusters)]
        scaled = [
            (value - mean) / scale if scale else 0.0
            for value, mean, scale in zip(features, self.mean, self.scale)
        ]
        logit = self.intercept + sum(weight * value for weight, value in zip(self.coefficients, scaled))
        return 1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, logit))))

