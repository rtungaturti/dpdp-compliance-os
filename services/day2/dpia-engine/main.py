"""
DPIA Engine — DPDP Compliance OS  Day 2
DPIA-as-code: auto-generates questionnaires, scores risk, drives
approval workflows via Temporal, and produces audit-ready reports.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import Counter, make_asgi_app
from pydantic import BaseModel, Field

log = structlog.get_logger()

app = FastAPI(title="DPIA Engine", version="1.0.0",
              description="DPIA-as-code with automated scoring and Temporal approval workflows")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/metrics", make_asgi_app())
FastAPIInstrumentor.instrument_app(app)

DPIAS_INITIATED   = Counter("dpia_initiated_total", "DPIAs started", ["risk_level"])
DPIAS_APPROVED    = Counter("dpia_approved_total",  "DPIAs approved")
DPIAS_REJECTED    = Counter("dpia_rejected_total",  "DPIAs rejected")


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------
class RiskLevel(str, Enum):
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


class DPIAStatus(str, Enum):
    DRAFT            = "draft"
    IN_REVIEW        = "in_review"
    DPO_APPROVAL     = "dpo_approval"
    BOARD_APPROVAL   = "board_approval"
    APPROVED         = "approved"
    REJECTED         = "rejected"
    REQUIRES_CONSULT = "requires_dpb_consultation"


class RiskCategory(BaseModel):
    category: str
    score: int          # 0–25 per category; 4 categories = 100 max
    rationale: str
    mitigations: list[str]


class DPIAInitiateRequest(BaseModel):
    project_id: str
    project_name: str
    data_controller_id: str
    processing_description: str
    data_categories: list[str]
    data_subjects_count: int
    includes_children: bool = False
    includes_sensitive_data: bool = False
    uses_automated_decision_making: bool = False
    involves_cross_border_transfer: bool = False
    new_technology_involved: bool = False
    processing_at_large_scale: bool = False
    systematic_monitoring: bool = False
    data_matching_profiling: bool = False
    requested_by: str
    business_justification: str


class DPIAReport(BaseModel):
    dpia_id: str
    project_id: str
    project_name: str
    status: DPIAStatus
    risk_level: RiskLevel
    overall_score: int   # 0–100
    risk_categories: list[RiskCategory]
    mandatory_measures: list[str]
    recommended_measures: list[str]
    dpb_consultation_required: bool
    approval_workflow_id: Optional[str]
    initiated_at: str
    initiated_by: str


# ---------------------------------------------------------------------------
# Risk scoring engine
# ---------------------------------------------------------------------------
RISK_WEIGHTS = {
    "includes_children":              15,
    "includes_sensitive_data":        12,
    "uses_automated_decision_making": 10,
    "involves_cross_border_transfer":  8,
    "new_technology_involved":         8,
    "processing_at_large_scale":       7,
    "systematic_monitoring":           7,
    "data_matching_profiling":         6,
}

MANDATORY_MEASURES_BY_TRIGGER = {
    "includes_children": [
        "Obtain verifiable parental/guardian consent (DPDP §9)",
        "Age verification mechanism before data collection",
        "No behavioural targeting of children",
        "Child-friendly privacy notice in plain language",
    ],
    "uses_automated_decision_making": [
        "Human override mechanism for all automated decisions",
        "Explainability report for decision logic",
        "Right to contest automated decisions (DPDP §11)",
        "Bias audit before deployment",
    ],
    "involves_cross_border_transfer": [
        "Verify destination country on MeitY whitelist",
        "Standard contractual clauses or binding corporate rules",
        "Transfer impact assessment",
        "Log all cross-border transfers in real-time",
    ],
    "includes_sensitive_data": [
        "Explicit consent for each sensitive category",
        "Encryption at rest (AES-256) and in transit (TLS 1.3+)",
        "Role-based access with MFA for sensitive data stores",
        "Breach notification within 72 hours to DPB",
    ],
}


def score_dpia(req: DPIAInitiateRequest) -> tuple[int, list[RiskCategory], list[str]]:
    score = 0
    mandatory: list[str] = []
    categories: list[RiskCategory] = []

    for field, weight in RISK_WEIGHTS.items():
        if getattr(req, field, False):
            score += weight
            measures = MANDATORY_MEASURES_BY_TRIGGER.get(field, [])
            mandatory.extend(measures)

            categories.append(RiskCategory(
                category=field.replace("_", " ").title(),
                score=weight,
                rationale=f"Processing activity involves {field.replace('_', ' ')}",
                mitigations=measures if measures else ["Apply data minimisation principle"],
            ))

    # Scale adjustment for subject count
    if req.data_subjects_count > 1_000_000:
        score = min(100, score + 10)
    elif req.data_subjects_count > 100_000:
        score = min(100, score + 5)

    return score, categories, list(set(mandatory))


def risk_level_from_score(score: int) -> RiskLevel:
    if score < 20:
        return RiskLevel.LOW
    if score < 45:
        return RiskLevel.MEDIUM
    if score < 70:
        return RiskLevel.HIGH
    return RiskLevel.CRITICAL


def approval_workflow(risk: RiskLevel) -> DPIAStatus:
    mapping = {
        RiskLevel.LOW:      DPIAStatus.APPROVED,
        RiskLevel.MEDIUM:   DPIAStatus.DPO_APPROVAL,
        RiskLevel.HIGH:     DPIAStatus.BOARD_APPROVAL,
        RiskLevel.CRITICAL: DPIAStatus.REQUIRES_CONSULT,
    }
    return mapping[risk]


RECOMMENDED_MEASURES = [
    "Privacy by Design review before architecture is finalised",
    "Data minimisation: collect only what's strictly necessary",
    "Retention schedule: auto-delete after defined period",
    "Annual re-assessment of this DPIA",
    "Vendor sub-processor due diligence",
]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "service": "dpia-engine"}


@app.post("/dpia/initiate", response_model=DPIAReport)
async def initiate_dpia(req: DPIAInitiateRequest):
    """Start a DPIA, auto-score risk, and trigger the appropriate approval workflow."""
    score, categories, mandatory = score_dpia(req)
    risk = risk_level_from_score(score)
    status = approval_workflow(risk)
    dpia_id = str(uuid.uuid4())

    # For non-trivial DPIAs, create a Temporal workflow (placeholder — wire to temporal in prod)
    workflow_id = None
    if risk in (RiskLevel.HIGH, RiskLevel.CRITICAL, RiskLevel.MEDIUM):
        workflow_id = f"dpia-approval-{dpia_id}"
        log.info("dpia.workflow.queued", workflow_id=workflow_id, risk=risk.value)

    DPIAS_INITIATED.labels(risk_level=risk.value).inc()
    log.info("dpia.initiated", dpia_id=dpia_id, project=req.project_name, risk=risk.value, score=score)

    return DPIAReport(
        dpia_id=dpia_id,
        project_id=req.project_id,
        project_name=req.project_name,
        status=status,
        risk_level=risk,
        overall_score=score,
        risk_categories=categories,
        mandatory_measures=mandatory,
        recommended_measures=RECOMMENDED_MEASURES,
        dpb_consultation_required=(risk == RiskLevel.CRITICAL),
        approval_workflow_id=workflow_id,
        initiated_at=datetime.now(timezone.utc).isoformat(),
        initiated_by=req.requested_by,
    )


@app.get("/dpia/{dpia_id}")
async def get_dpia(dpia_id: str):
    # In production: fetch from DB
    raise HTTPException(501, "Database integration pending")


@app.post("/dpia/{dpia_id}/approve")
async def approve_dpia(dpia_id: str, approver_id: str, notes: str = ""):
    DPIAS_APPROVED.inc()
    log.info("dpia.approved", dpia_id=dpia_id, approver=approver_id)
    return {"dpia_id": dpia_id, "status": DPIAStatus.APPROVED, "approved_by": approver_id}


@app.post("/dpia/{dpia_id}/reject")
async def reject_dpia(dpia_id: str, approver_id: str, reason: str):
    DPIAS_REJECTED.inc()
    log.info("dpia.rejected", dpia_id=dpia_id, approver=approver_id, reason=reason)
    return {"dpia_id": dpia_id, "status": DPIAStatus.REJECTED, "reason": reason}


@app.get("/dpia/templates/questionnaire")
async def get_questionnaire():
    """Returns the standard DPIA questionnaire aligned to DPDP Act 2023."""
    return {
        "sections": [
            {"id": "s1", "title": "Processing Description", "questions": [
                {"id": "q1", "text": "Describe the processing activity in plain language", "type": "textarea"},
                {"id": "q2", "text": "What is the business purpose?", "type": "textarea"},
                {"id": "q3", "text": "Is this a new processing activity or change to existing?", "type": "boolean"},
            ]},
            {"id": "s2", "title": "Data Subjects", "questions": [
                {"id": "q4", "text": "How many data principals are affected?", "type": "number"},
                {"id": "q5", "text": "Does processing include children under 18?", "type": "boolean"},
                {"id": "q6", "text": "Are data subjects aware of this processing?", "type": "boolean"},
            ]},
            {"id": "s3", "title": "Risk Factors (DPDP §10)", "questions": [
                {"id": "q7", "text": "Does processing involve sensitive personal data?", "type": "boolean"},
                {"id": "q8", "text": "Will automated decisions affect individuals?", "type": "boolean"},
                {"id": "q9", "text": "Is data transferred outside India?", "type": "boolean"},
                {"id": "q10", "text": "Does processing use new or experimental technology?", "type": "boolean"},
                {"id": "q11", "text": "Is systematic monitoring involved?", "type": "boolean"},
            ]},
        ]
    }
