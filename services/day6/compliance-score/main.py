"""
Compliance Score Engine — DPDP Compliance OS  Day 6
Credit-score-style DPDP compliance rating (0–1000) for organisations.
Aggregates signals from all Day 1–5 services to produce a live score.
Score is used by: penalty calculator, settlement optimizer, DPO console.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import Counter, Gauge, make_asgi_app
from pydantic import BaseModel, Field

log = structlog.get_logger()

app = FastAPI(title="Compliance Score Engine", version="1.0.0",
              description="DPDP compliance credit scoring — 0 to 1000 scale")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/metrics", make_asgi_app())
FastAPIInstrumentor.instrument_app(app)

SCORES_COMPUTED = Counter("compliance_scores_computed_total", "Scores computed", ["tier"])
CURRENT_SCORE   = Gauge("compliance_score_current", "Current compliance score", ["entity_id"])


# ---------------------------------------------------------------------------
# Scoring dimensions (weights sum to 1000)
# ---------------------------------------------------------------------------
class ScoreDimension(str, Enum):
    CONSENT_MANAGEMENT      = "consent_management"       # 200 pts
    DATA_RIGHTS_FULFILLMENT = "data_rights_fulfillment"  # 200 pts
    BREACH_RESPONSE         = "breach_response"          # 150 pts
    AI_GOVERNANCE           = "ai_governance"            # 150 pts
    DATA_MINIMISATION       = "data_minimisation"        # 100 pts
    CROSS_BORDER_COMPLIANCE = "cross_border_compliance"  # 100 pts
    DOCUMENTATION_AUDIT     = "documentation_audit"      # 100 pts


DIMENSION_WEIGHTS: dict[ScoreDimension, int] = {
    ScoreDimension.CONSENT_MANAGEMENT:      200,
    ScoreDimension.DATA_RIGHTS_FULFILLMENT: 200,
    ScoreDimension.BREACH_RESPONSE:         150,
    ScoreDimension.AI_GOVERNANCE:           150,
    ScoreDimension.DATA_MINIMISATION:       100,
    ScoreDimension.CROSS_BORDER_COMPLIANCE: 100,
    ScoreDimension.DOCUMENTATION_AUDIT:     100,
}


class ComplianceTier(str, Enum):
    PLATINUM = "platinum"    # 900–1000
    GOLD     = "gold"        # 750–899
    SILVER   = "silver"      # 600–749
    BRONZE   = "bronze"      # 400–599
    AT_RISK  = "at_risk"     # 200–399
    CRITICAL = "critical"    # 0–199


def tier_from_score(score: int) -> ComplianceTier:
    if score >= 900: return ComplianceTier.PLATINUM
    if score >= 750: return ComplianceTier.GOLD
    if score >= 600: return ComplianceTier.SILVER
    if score >= 400: return ComplianceTier.BRONZE
    if score >= 200: return ComplianceTier.AT_RISK
    return ComplianceTier.CRITICAL


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class ConsentSignals(BaseModel):
    total_consents: int = 0
    valid_consents: int = 0
    withdrawal_response_avg_hours: float = 0
    child_consent_compliant: bool = True
    consent_receipts_issued: bool = False


class RightsSignals(BaseModel):
    total_requests: int = 0
    completed_on_time: int = 0
    average_response_days: float = 0
    automated_fulfillment_rate: float = 0


class BreachSignals(BaseModel):
    breaches_last_12m: int = 0
    avg_detection_hours: float = 0
    avg_notification_hours: float = 0   # DPB notification SLA: 72h
    remediation_complete: bool = True


class AIGovernanceSignals(BaseModel):
    ai_systems_inventoried: bool = False
    dpias_completed: int = 0
    bias_evaluations_run: int = 0
    algorithmic_report_published: bool = False
    dpo_appointed: bool = False


class ScoreRequest(BaseModel):
    entity_id: str
    entity_name: str
    consent: ConsentSignals = ConsentSignals()
    rights: RightsSignals = RightsSignals()
    breach: BreachSignals = BreachSignals()
    ai_governance: AIGovernanceSignals = AIGovernanceSignals()
    cross_border_violations_last_12m: int = 0
    data_minimisation_score: float = Field(0.7, ge=0, le=1)
    documentation_completeness: float = Field(0.5, ge=0, le=1)


class DimensionScore(BaseModel):
    dimension: ScoreDimension
    raw_score: int
    max_score: int
    percentage: float
    deductions: list[str]
    improvements: list[str]


class ComplianceScoreResponse(BaseModel):
    score_id: str
    entity_id: str
    entity_name: str
    total_score: int
    max_score: int = 1000
    tier: ComplianceTier
    tier_description: str
    dimension_scores: list[DimensionScore]
    top_risks: list[str]
    quick_wins: list[str]
    penalty_reduction_eligible: bool
    computed_at: str
    valid_until: str


# ---------------------------------------------------------------------------
# Scoring logic
# ---------------------------------------------------------------------------
TIER_DESCRIPTIONS = {
    ComplianceTier.PLATINUM: "Exemplary DPDP compliance — eligible for self-certification",
    ComplianceTier.GOLD:     "Strong compliance posture — minor gaps only",
    ComplianceTier.SILVER:   "Adequate compliance — improvement areas identified",
    ComplianceTier.BRONZE:   "Compliance gaps present — remediation plan required",
    ComplianceTier.AT_RISK:  "Significant non-compliance — regulatory risk elevated",
    ComplianceTier.CRITICAL: "Critical non-compliance — immediate action required",
}


def score_consent(signals: ConsentSignals, max_pts: int) -> tuple[int, list[str], list[str]]:
    deductions, improvements = [], []
    pts = max_pts

    if signals.total_consents == 0:
        deductions.append("No consent records found")
        return 0, deductions, improvements

    rate = signals.valid_consents / signals.total_consents if signals.total_consents else 0
    pts = int(pts * rate)

    if signals.withdrawal_response_avg_hours > 24:
        penalty = int(max_pts * 0.1)
        pts -= penalty
        deductions.append(f"Withdrawal response avg {signals.withdrawal_response_avg_hours:.0f}h (>24h SLA)")
    if not signals.child_consent_compliant:
        pts -= int(max_pts * 0.2)
        deductions.append("Child consent non-compliant (DPDP §9 violation)")
    if not signals.consent_receipts_issued:
        pts -= int(max_pts * 0.05)
        improvements.append("Issue signed consent receipts to all principals")

    return max(0, pts), deductions, improvements


def score_rights(signals: RightsSignals, max_pts: int) -> tuple[int, list[str], list[str]]:
    deductions, improvements = [], []
    if signals.total_requests == 0:
        return max_pts, deductions, ["Record and track all rights requests"]

    on_time_rate = signals.completed_on_time / signals.total_requests
    pts = int(max_pts * on_time_rate)

    if signals.average_response_days > 25:
        pts -= int(max_pts * 0.15)
        deductions.append(f"Avg response {signals.average_response_days:.0f} days — approaching 30-day limit")
    if signals.automated_fulfillment_rate < 0.3:
        improvements.append("Automate rights fulfillment — current rate <30%")

    return max(0, pts), deductions, improvements


def score_breach(signals: BreachSignals, max_pts: int) -> tuple[int, list[str], list[str]]:
    deductions, improvements = [], []
    pts = max_pts

    pts -= min(max_pts // 2, signals.breaches_last_12m * 30)
    if signals.breaches_last_12m > 0:
        deductions.append(f"{signals.breaches_last_12m} breach(es) in last 12 months")

    if signals.avg_notification_hours > 72:
        pts -= int(max_pts * 0.2)
        deductions.append(f"Avg DPB notification {signals.avg_notification_hours:.0f}h (>72h DPDP requirement)")
    if not signals.remediation_complete:
        pts -= int(max_pts * 0.1)
        deductions.append("Open breach remediations pending")

    return max(0, pts), deductions, improvements


def score_ai(signals: AIGovernanceSignals, max_pts: int) -> tuple[int, list[str], list[str]]:
    deductions, improvements = [], []
    pts = 0

    if signals.ai_systems_inventoried:
        pts += int(max_pts * 0.25)
    else:
        improvements.append("Complete AI systems inventory (required for SDF)")

    pts += min(int(max_pts * 0.25), signals.dpias_completed * 15)
    pts += min(int(max_pts * 0.2), signals.bias_evaluations_run * 10)

    if signals.algorithmic_report_published:
        pts += int(max_pts * 0.2)
    else:
        improvements.append("Publish algorithmic accountability report (DPDP §10(3)(b))")

    if signals.dpo_appointed:
        pts += int(max_pts * 0.1)
    else:
        deductions.append("DPO not appointed — mandatory for SDF (DPDP §10(1))")

    return min(max_pts, pts), deductions, improvements


def compute_score(req: ScoreRequest) -> ComplianceScoreResponse:
    dimension_scores: list[DimensionScore] = []
    total = 0
    all_deductions: list[str] = []
    all_improvements: list[str] = []

    # Consent
    c_pts, c_ded, c_imp = score_consent(req.consent, DIMENSION_WEIGHTS[ScoreDimension.CONSENT_MANAGEMENT])
    dimension_scores.append(DimensionScore(
        dimension=ScoreDimension.CONSENT_MANAGEMENT,
        raw_score=c_pts, max_score=DIMENSION_WEIGHTS[ScoreDimension.CONSENT_MANAGEMENT],
        percentage=round(c_pts / DIMENSION_WEIGHTS[ScoreDimension.CONSENT_MANAGEMENT] * 100, 1),
        deductions=c_ded, improvements=c_imp,
    ))
    total += c_pts; all_deductions += c_ded; all_improvements += c_imp

    # Rights
    r_pts, r_ded, r_imp = score_rights(req.rights, DIMENSION_WEIGHTS[ScoreDimension.DATA_RIGHTS_FULFILLMENT])
    dimension_scores.append(DimensionScore(
        dimension=ScoreDimension.DATA_RIGHTS_FULFILLMENT,
        raw_score=r_pts, max_score=DIMENSION_WEIGHTS[ScoreDimension.DATA_RIGHTS_FULFILLMENT],
        percentage=round(r_pts / DIMENSION_WEIGHTS[ScoreDimension.DATA_RIGHTS_FULFILLMENT] * 100, 1),
        deductions=r_ded, improvements=r_imp,
    ))
    total += r_pts; all_deductions += r_ded; all_improvements += r_imp

    # Breach
    b_pts, b_ded, b_imp = score_breach(req.breach, DIMENSION_WEIGHTS[ScoreDimension.BREACH_RESPONSE])
    dimension_scores.append(DimensionScore(
        dimension=ScoreDimension.BREACH_RESPONSE,
        raw_score=b_pts, max_score=DIMENSION_WEIGHTS[ScoreDimension.BREACH_RESPONSE],
        percentage=round(b_pts / DIMENSION_WEIGHTS[ScoreDimension.BREACH_RESPONSE] * 100, 1),
        deductions=b_ded, improvements=b_imp,
    ))
    total += b_pts; all_deductions += b_ded; all_improvements += b_imp

    # AI Governance
    ai_pts, ai_ded, ai_imp = score_ai(req.ai_governance, DIMENSION_WEIGHTS[ScoreDimension.AI_GOVERNANCE])
    dimension_scores.append(DimensionScore(
        dimension=ScoreDimension.AI_GOVERNANCE,
        raw_score=ai_pts, max_score=DIMENSION_WEIGHTS[ScoreDimension.AI_GOVERNANCE],
        percentage=round(ai_pts / DIMENSION_WEIGHTS[ScoreDimension.AI_GOVERNANCE] * 100, 1),
        deductions=ai_ded, improvements=ai_imp,
    ))
    total += ai_pts; all_deductions += ai_ded; all_improvements += ai_imp

    # Cross-border
    cb_max = DIMENSION_WEIGHTS[ScoreDimension.CROSS_BORDER_COMPLIANCE]
    cb_pts = max(0, cb_max - (req.cross_border_violations_last_12m * 25))
    cb_ded = [f"{req.cross_border_violations_last_12m} cross-border violation(s)"] if req.cross_border_violations_last_12m else []
    dimension_scores.append(DimensionScore(
        dimension=ScoreDimension.CROSS_BORDER_COMPLIANCE,
        raw_score=cb_pts, max_score=cb_max,
        percentage=round(cb_pts / cb_max * 100, 1),
        deductions=cb_ded, improvements=[],
    ))
    total += cb_pts; all_deductions += cb_ded

    # Data minimisation
    dm_max = DIMENSION_WEIGHTS[ScoreDimension.DATA_MINIMISATION]
    dm_pts = int(dm_max * req.data_minimisation_score)
    dimension_scores.append(DimensionScore(
        dimension=ScoreDimension.DATA_MINIMISATION,
        raw_score=dm_pts, max_score=dm_max,
        percentage=round(req.data_minimisation_score * 100, 1),
        deductions=[] if req.data_minimisation_score >= 0.8 else ["Data minimisation score below 80%"],
        improvements=[] if req.data_minimisation_score >= 0.9 else ["Implement data retention automation"],
    ))
    total += dm_pts

    # Documentation
    doc_max = DIMENSION_WEIGHTS[ScoreDimension.DOCUMENTATION_AUDIT]
    doc_pts = int(doc_max * req.documentation_completeness)
    dimension_scores.append(DimensionScore(
        dimension=ScoreDimension.DOCUMENTATION_AUDIT,
        raw_score=doc_pts, max_score=doc_max,
        percentage=round(req.documentation_completeness * 100, 1),
        deductions=[] if req.documentation_completeness >= 0.8 else ["Documentation <80% complete"],
        improvements=["Complete ROPA, processing agreements, and DPIAs"],
    ))
    total += doc_pts

    tier = tier_from_score(total)
    now = datetime.now(timezone.utc)
    valid_until = now.replace(day=1, month=now.month % 12 + 1) if now.month < 12 else now.replace(year=now.year+1, month=1, day=1)

    SCORES_COMPUTED.labels(tier=tier.value).inc()
    CURRENT_SCORE.labels(entity_id=req.entity_id).set(total)
    log.info("compliance.score.computed", entity_id=req.entity_id, score=total, tier=tier.value)

    return ComplianceScoreResponse(
        score_id=str(uuid.uuid4()),
        entity_id=req.entity_id,
        entity_name=req.entity_name,
        total_score=total,
        tier=tier,
        tier_description=TIER_DESCRIPTIONS[tier],
        dimension_scores=dimension_scores,
        top_risks=all_deductions[:5],
        quick_wins=all_improvements[:5],
        penalty_reduction_eligible=(tier in (ComplianceTier.GOLD, ComplianceTier.PLATINUM)),
        computed_at=now.isoformat(),
        valid_until=valid_until.isoformat(),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "service": "compliance-score"}

@app.post("/score/compute", response_model=ComplianceScoreResponse)
async def compute(req: ScoreRequest):
    return compute_score(req)

@app.get("/score/dimensions")
async def get_dimensions():
    return {"dimensions": DIMENSION_WEIGHTS, "total_max": 1000}

@app.get("/score/tiers")
async def get_tiers():
    return {"tiers": {
        "platinum": {"min": 900, "max": 1000, "description": TIER_DESCRIPTIONS[ComplianceTier.PLATINUM]},
        "gold":     {"min": 750, "max": 899,  "description": TIER_DESCRIPTIONS[ComplianceTier.GOLD]},
        "silver":   {"min": 600, "max": 749,  "description": TIER_DESCRIPTIONS[ComplianceTier.SILVER]},
        "bronze":   {"min": 400, "max": 599,  "description": TIER_DESCRIPTIONS[ComplianceTier.BRONZE]},
        "at_risk":  {"min": 200, "max": 399,  "description": TIER_DESCRIPTIONS[ComplianceTier.AT_RISK]},
        "critical": {"min": 0,   "max": 199,  "description": TIER_DESCRIPTIONS[ComplianceTier.CRITICAL]},
    }}
