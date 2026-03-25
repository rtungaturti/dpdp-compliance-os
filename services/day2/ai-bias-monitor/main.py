"""
AI Bias Monitor — DPDP Compliance OS  Day 2
Tracks fairness metrics across AI/ML models, detects bias drift,
and triggers alerts when thresholds breach DPDP/EU AI Act standards.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import math

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import Counter, Gauge, make_asgi_app
from pydantic import BaseModel, Field

log = structlog.get_logger()

app = FastAPI(title="AI Bias Monitor", version="1.0.0",
              description="Fairness metrics, bias drift detection, and algorithmic accountability")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/metrics", make_asgi_app())
FastAPIInstrumentor.instrument_app(app)

BIAS_ALERTS    = Counter("bias_alerts_total", "Bias threshold breaches", ["metric", "model_id"])
FAIRNESS_SCORE = Gauge("model_fairness_score", "Current fairness score per model", ["model_id"])


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------
class ProtectedAttribute(str, Enum):
    GENDER    = "gender"
    AGE       = "age"
    RELIGION  = "religion"
    CASTE     = "caste"
    ETHNICITY = "ethnicity"
    DISABILITY = "disability"
    REGION    = "region"


class FairnessMetric(str, Enum):
    DEMOGRAPHIC_PARITY      = "demographic_parity"
    EQUAL_OPPORTUNITY       = "equal_opportunity"
    EQUALIZED_ODDS          = "equalized_odds"
    INDIVIDUAL_FAIRNESS     = "individual_fairness"
    COUNTERFACTUAL_FAIRNESS = "counterfactual_fairness"
    CALIBRATION             = "calibration"


class BiasLevel(str, Enum):
    ACCEPTABLE  = "acceptable"
    BORDERLINE  = "borderline"
    CONCERNING  = "concerning"
    CRITICAL    = "critical"


class GroupMetrics(BaseModel):
    group_name: str
    protected_attribute: ProtectedAttribute
    group_size: int
    positive_rate: float = Field(..., ge=0, le=1)
    true_positive_rate: float = Field(..., ge=0, le=1)
    false_positive_rate: float = Field(..., ge=0, le=1)
    false_negative_rate: float = Field(..., ge=0, le=1)


class BiasEvaluationRequest(BaseModel):
    model_id: str
    model_name: str
    model_version: str
    evaluation_dataset_id: str
    group_metrics: list[GroupMetrics] = Field(..., min_length=2)
    reference_group: str
    use_case: str
    evaluated_by: str


class MetricResult(BaseModel):
    metric: FairnessMetric
    value: float
    threshold: float
    passed: bool
    interpretation: str
    affected_groups: list[str]


class BiasEvaluationReport(BaseModel):
    evaluation_id: str
    model_id: str
    model_name: str
    model_version: str
    overall_fairness_score: float   # 0–1
    bias_level: BiasLevel
    metric_results: list[MetricResult]
    bias_detected: bool
    at_risk_groups: list[str]
    mandatory_actions: list[str]
    recommendations: list[str]
    evaluated_at: str
    evaluated_by: str


# ---------------------------------------------------------------------------
# Fairness thresholds (configurable per use case in production)
# ---------------------------------------------------------------------------
THRESHOLDS = {
    FairnessMetric.DEMOGRAPHIC_PARITY:  0.80,  # ratio of positive rates ≥ 0.8
    FairnessMetric.EQUAL_OPPORTUNITY:   0.80,
    FairnessMetric.EQUALIZED_ODDS:      0.80,
    FairnessMetric.CALIBRATION:         0.05,  # max calibration gap
}

MANDATORY_ACTIONS = {
    BiasLevel.CONCERNING: [
        "Freeze model deployment pending bias investigation",
        "Root cause analysis: training data, labelling, feature selection",
        "Engage affected community for participatory audit",
        "Document in algorithmic accountability report (DPDP §10(3)(b))",
    ],
    BiasLevel.CRITICAL: [
        "IMMEDIATE: Suspend model in production",
        "Notify DPO and Board within 24 hours",
        "Conduct emergency DPIA reassessment",
        "Notify Data Protection Board if model affects >1L individuals",
        "Independent fairness audit before re-deployment",
        "Remediate training data and retrain from scratch",
    ],
}


# ---------------------------------------------------------------------------
# Computation
# ---------------------------------------------------------------------------
def compute_demographic_parity(groups: list[GroupMetrics], ref_group: str) -> tuple[float, list[str]]:
    ref = next((g for g in groups if g.group_name == ref_group), groups[0])
    at_risk = []
    min_ratio = 1.0
    for g in groups:
        if g.group_name == ref_group:
            continue
        if ref.positive_rate == 0:
            continue
        ratio = g.positive_rate / ref.positive_rate
        min_ratio = min(min_ratio, ratio)
        if ratio < THRESHOLDS[FairnessMetric.DEMOGRAPHIC_PARITY]:
            at_risk.append(g.group_name)
    return min_ratio, at_risk


def compute_equal_opportunity(groups: list[GroupMetrics], ref_group: str) -> tuple[float, list[str]]:
    ref = next((g for g in groups if g.group_name == ref_group), groups[0])
    at_risk = []
    min_ratio = 1.0
    for g in groups:
        if g.group_name == ref_group:
            continue
        if ref.true_positive_rate == 0:
            continue
        ratio = g.true_positive_rate / ref.true_positive_rate
        min_ratio = min(min_ratio, ratio)
        if ratio < THRESHOLDS[FairnessMetric.EQUAL_OPPORTUNITY]:
            at_risk.append(g.group_name)
    return min_ratio, at_risk


def evaluate_bias(req: BiasEvaluationRequest) -> BiasEvaluationReport:
    metric_results: list[MetricResult] = []
    all_at_risk: set[str] = set()

    # Demographic parity
    dp_value, dp_at_risk = compute_demographic_parity(req.group_metrics, req.reference_group)
    all_at_risk.update(dp_at_risk)
    metric_results.append(MetricResult(
        metric=FairnessMetric.DEMOGRAPHIC_PARITY,
        value=round(dp_value, 4),
        threshold=THRESHOLDS[FairnessMetric.DEMOGRAPHIC_PARITY],
        passed=dp_value >= THRESHOLDS[FairnessMetric.DEMOGRAPHIC_PARITY],
        interpretation=f"Minimum positive rate ratio vs reference group: {dp_value:.2%}",
        affected_groups=dp_at_risk,
    ))

    # Equal opportunity
    eo_value, eo_at_risk = compute_equal_opportunity(req.group_metrics, req.reference_group)
    all_at_risk.update(eo_at_risk)
    metric_results.append(MetricResult(
        metric=FairnessMetric.EQUAL_OPPORTUNITY,
        value=round(eo_value, 4),
        threshold=THRESHOLDS[FairnessMetric.EQUAL_OPPORTUNITY],
        passed=eo_value >= THRESHOLDS[FairnessMetric.EQUAL_OPPORTUNITY],
        interpretation=f"Minimum TPR ratio vs reference group: {eo_value:.2%}",
        affected_groups=eo_at_risk,
    ))

    failures = sum(1 for r in metric_results if not r.passed)
    fairness_score = round(1.0 - (failures / len(metric_results)), 2)

    bias_detected = failures > 0
    bias_level = (
        BiasLevel.CRITICAL   if failures >= 2 and len(all_at_risk) > 2 else
        BiasLevel.CONCERNING if failures >= 1 else
        BiasLevel.BORDERLINE if fairness_score < 0.95 else
        BiasLevel.ACCEPTABLE
    )

    mandatory = MANDATORY_ACTIONS.get(bias_level, [])
    recommendations = [
        "Re-evaluate training dataset for representation gaps",
        "Apply reweighting or resampling to underrepresented groups",
        "Consider fairness constraints during model training",
        "Implement ongoing monitoring with monthly bias reports",
        "Publish bias metrics in annual algorithmic accountability report",
    ]

    FAIRNESS_SCORE.labels(model_id=req.model_id).set(fairness_score)
    if bias_detected:
        for m in metric_results:
            if not m.passed:
                BIAS_ALERTS.labels(metric=m.metric.value, model_id=req.model_id).inc()

    log.info("bias.evaluated", model_id=req.model_id, bias_level=bias_level.value, fairness_score=fairness_score, at_risk=list(all_at_risk))

    return BiasEvaluationReport(
        evaluation_id=str(uuid.uuid4()),
        model_id=req.model_id,
        model_name=req.model_name,
        model_version=req.model_version,
        overall_fairness_score=fairness_score,
        bias_level=bias_level,
        metric_results=metric_results,
        bias_detected=bias_detected,
        at_risk_groups=list(all_at_risk),
        mandatory_actions=mandatory,
        recommendations=recommendations,
        evaluated_at=datetime.now(timezone.utc).isoformat(),
        evaluated_by=req.evaluated_by,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "service": "ai-bias-monitor"}

@app.post("/bias/evaluate", response_model=BiasEvaluationReport)
async def evaluate(req: BiasEvaluationRequest):
    """Run full fairness evaluation across protected attributes."""
    return evaluate_bias(req)

@app.get("/bias/thresholds")
async def get_thresholds():
    return {"thresholds": {k.value: v for k, v in THRESHOLDS.items()}, "standard": "DPDP §10 + EU AI Act Article 10"}

@app.get("/bias/protected-attributes")
async def protected_attributes():
    return {"attributes": [a.value for a in ProtectedAttribute], "source": "DPDP Act 2023 + Indian Constitution Articles 14-16"}

@app.get("/bias/models/{model_id}/history")
async def model_history(model_id: str):
    # In production: fetch from TimescaleDB
    return {"model_id": model_id, "evaluations": [], "note": "Connect TimescaleDB for history"}
