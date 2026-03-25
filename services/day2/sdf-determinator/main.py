"""
SDF Determinator — DPDP Compliance OS  Day 2
Classifies Significant Data Fiduciaries per DPDP §10 + Schedule I,
generates obligation checklists, and drives DPIA/audit triggers.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import uuid

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import Counter, Histogram, make_asgi_app
from pydantic import BaseModel, Field

log = structlog.get_logger()

app = FastAPI(title="SDF Determinator", version="1.0.0",
              description="DPDP §10 Significant Data Fiduciary classification and obligations")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/metrics", make_asgi_app())
FastAPIInstrumentor.instrument_app(app)

SDF_CLASSIFICATIONS = Counter("sdf_classifications_total", "SDF determinations", ["result"])
OBLIGATION_LOOKUPS  = Counter("sdf_obligation_lookups_total", "Obligation lookups")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class SDFTrigger(str, Enum):
    LARGE_SCALE_PROCESSING = "large_scale_processing"   # >1Cr principals
    SENSITIVE_DATA         = "sensitive_data"
    CHILDREN_DATA          = "children_data"
    NATIONAL_SECURITY      = "national_security"
    AI_PROFILING           = "ai_profiling"
    CROSS_BORDER           = "cross_border_significant"
    HIGH_TURNOVER          = "high_turnover"


class SDFObligation(BaseModel):
    code: str
    section: str
    title: str
    description: str
    deadline_days: Optional[int] = None
    is_recurring: bool = False
    recurrence: Optional[str] = None


class SDFDeterminationRequest(BaseModel):
    entity_id: str
    entity_name: str
    principal_count: int = Field(..., ge=0)
    processes_sensitive_data: bool = False
    sensitive_categories: list[str] = []
    processes_children_data: bool = False
    turnover_crore: float = 0.0
    operates_ai_systems: bool = False
    ai_system_count: int = 0
    cross_border_volume_gb_month: float = 0.0
    sector: str = "other"


class SDFDeterminationResponse(BaseModel):
    determination_id: str
    entity_id: str
    is_sdf: bool
    triggers: list[SDFTrigger]
    obligations: list[SDFObligation]
    dpia_required: bool
    independent_audit_required: bool
    dpo_mandatory: bool
    risk_tier: str   # LOW / MEDIUM / HIGH / CRITICAL
    determined_at: str
    next_review_date: str


# ---------------------------------------------------------------------------
# Obligation library (DPDP §10 + Rules 2024)
# ---------------------------------------------------------------------------
SDF_OBLIGATIONS: list[SDFObligation] = [
    SDFObligation(
        code="SDF-01", section="§10(1)", title="Appoint Data Protection Officer",
        description="Designate a qualified DPO who reports directly to the Board. DPO must be accessible to data principals.",
        deadline_days=90, is_recurring=False,
    ),
    SDFObligation(
        code="SDF-02", section="§10(2)", title="Appoint Independent Data Auditor",
        description="Engage an independent auditor to evaluate compliance annually. Auditor must be empanelled by the Data Protection Board.",
        deadline_days=180, is_recurring=True, recurrence="annual",
    ),
    SDFObligation(
        code="SDF-03", section="§10(3)(a)", title="Data Protection Impact Assessment",
        description="Conduct DPIA before any new processing activity that involves SDFs or high-risk processing. Submit summary to DPB.",
        deadline_days=30, is_recurring=True, recurrence="per_new_activity",
    ),
    SDFObligation(
        code="SDF-04", section="§10(3)(b)", title="Algorithmic Accountability Report",
        description="Publish periodic reports on AI/ML systems used for profiling, automated decisions, or content recommendation.",
        deadline_days=365, is_recurring=True, recurrence="annual",
    ),
    SDFObligation(
        code="SDF-05", section="§10(3)(c)", title="Cross-Border Transfer Restrictions",
        description="Personal data may only be transferred to countries whitelisted by Central Government. Maintain transfer records.",
        deadline_days=None, is_recurring=False,
    ),
    SDFObligation(
        code="SDF-06", section="§10(4)", title="Enhanced Security Standards",
        description="Implement security safeguards exceeding baseline: encryption at rest+transit, access controls, breach detection.",
        deadline_days=60, is_recurring=False,
    ),
    SDFObligation(
        code="SDF-07", section="§10(5)", title="Consent Manager Registration",
        description="Register with or integrate a DPB-approved Consent Manager for managing data principal consents at scale.",
        deadline_days=120, is_recurring=False,
    ),
    SDFObligation(
        code="SDF-08", section="§11", title="Rights Request SLA",
        description="Respond to all data principal rights requests within 30 days. Automated escalation for SDF-level volume.",
        deadline_days=30, is_recurring=True, recurrence="per_request",
    ),
]


# ---------------------------------------------------------------------------
# Determination logic
# ---------------------------------------------------------------------------
THRESHOLDS = {
    "principal_count": 10_000_000,
    "turnover_crore": 500,
    "cross_border_gb": 10,
    "ai_systems": 3,
}

def determine_sdf(req: SDFDeterminationRequest) -> SDFDeterminationResponse:
    triggers: list[SDFTrigger] = []

    if req.principal_count >= THRESHOLDS["principal_count"]:
        triggers.append(SDFTrigger.LARGE_SCALE_PROCESSING)
    if req.processes_sensitive_data:
        triggers.append(SDFTrigger.SENSITIVE_DATA)
    if req.processes_children_data:
        triggers.append(SDFTrigger.CHILDREN_DATA)
    if req.turnover_crore >= THRESHOLDS["turnover_crore"]:
        triggers.append(SDFTrigger.HIGH_TURNOVER)
    if req.operates_ai_systems and req.ai_system_count >= THRESHOLDS["ai_systems"]:
        triggers.append(SDFTrigger.AI_PROFILING)
    if req.cross_border_volume_gb_month >= THRESHOLDS["cross_border_gb"]:
        triggers.append(SDFTrigger.CROSS_BORDER)

    is_sdf = len(triggers) > 0

    # Risk tier
    score = (
        (2 if SDFTrigger.LARGE_SCALE_PROCESSING in triggers else 0) +
        (2 if SDFTrigger.SENSITIVE_DATA in triggers else 0) +
        (3 if SDFTrigger.CHILDREN_DATA in triggers else 0) +
        (1 if SDFTrigger.AI_PROFILING in triggers else 0) +
        (1 if SDFTrigger.CROSS_BORDER in triggers else 0)
    )
    risk_tier = "LOW" if not is_sdf else ("MEDIUM" if score <= 2 else ("HIGH" if score <= 4 else "CRITICAL"))

    now = datetime.now(timezone.utc)
    next_review = now.replace(year=now.year + 1)

    obligations = SDF_OBLIGATIONS if is_sdf else []

    SDF_CLASSIFICATIONS.labels(result="sdf" if is_sdf else "non-sdf").inc()
    log.info("sdf.determined", entity_id=req.entity_id, is_sdf=is_sdf, risk_tier=risk_tier, triggers=[t.value for t in triggers])

    return SDFDeterminationResponse(
        determination_id=str(uuid.uuid4()),
        entity_id=req.entity_id,
        is_sdf=is_sdf,
        triggers=triggers,
        obligations=obligations,
        dpia_required=is_sdf or req.operates_ai_systems,
        independent_audit_required=is_sdf,
        dpo_mandatory=is_sdf,
        risk_tier=risk_tier,
        determined_at=now.isoformat(),
        next_review_date=next_review.isoformat(),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "service": "sdf-determinator"}

@app.post("/sdf/determine", response_model=SDFDeterminationResponse)
async def determine(req: SDFDeterminationRequest):
    """Determine SDF status and return full obligation set."""
    return determine_sdf(req)

@app.get("/sdf/obligations")
async def list_obligations():
    """Return the full DPDP SDF obligation library."""
    OBLIGATION_LOOKUPS.inc()
    return {"obligations": SDF_OBLIGATIONS, "count": len(SDF_OBLIGATIONS)}

@app.get("/sdf/thresholds")
async def get_thresholds():
    return {"thresholds": THRESHOLDS, "source": "DPDP Act 2023 §10 + Schedule I"}

@app.post("/sdf/batch")
async def batch_determine(requests: list[SDFDeterminationRequest]):
    if len(requests) > 50:
        raise HTTPException(422, "Batch size ≤ 50")
    return [determine_sdf(r) for r in requests]
