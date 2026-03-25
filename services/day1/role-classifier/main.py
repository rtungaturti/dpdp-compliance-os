"""
Role Classifier — DPDP Compliance OS  Day 1
Classifies entities as Data Fiduciary, Data Processor, or Significant
Data Fiduciary (SDF) per DPDP Act §2, §3, and Schedule I.
"""

from datetime import datetime, timezone
from enum import Enum

import structlog
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import Counter, make_asgi_app
from pydantic import BaseModel, Field

log = structlog.get_logger()

CLASSIFICATIONS = Counter(
    "role_classifications_total", "Role classifications issued", ["role", "is_sdf"]
)

app = FastAPI(
    title="Role Classifier",
    description="DPDP §2 entity classification and SDF determination",
    version="1.0.0",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)
FastAPIInstrumentor.instrument_app(app)


# ---------------------------------------------------------------------------
# Domain enums & schemas
# ---------------------------------------------------------------------------
class DPDPRole(str, Enum):
    DATA_FIDUCIARY = "data_fiduciary"
    DATA_PROCESSOR = "data_processor"
    SIGNIFICANT_DATA_FIDUCIARY = "significant_data_fiduciary"
    EXEMPT = "exempt"  # DPDP Schedule II exemptions


class SectorType(str, Enum):
    HEALTH = "health"
    FINANCE = "finance"
    TELECOM = "telecom"
    EDUCATION = "education"
    ECOMMERCE = "ecommerce"
    SOCIAL_MEDIA = "social_media"
    GOVERNMENT = "government"
    OTHER = "other"


class ClassifyRequest(BaseModel):
    entity_id: str
    entity_name: str
    sector: SectorType
    user_count: int = Field(..., ge=0, description="Approximate number of data principals")
    processes_child_data: bool = False
    processes_sensitive_data: bool = False
    cross_border_transfers: bool = False
    ai_ml_profiling: bool = False
    is_govt_entity: bool = False
    annual_turnover_crore: float = Field(0.0, ge=0)
    is_data_processor_only: bool = False


class ClassifyResponse(BaseModel):
    entity_id: str
    role: DPDPRole
    is_sdf: bool
    sdf_triggers: list[str]
    obligations: list[str]
    risk_score: int  # 0–100
    classification_id: str
    classified_at: str


# ---------------------------------------------------------------------------
# Classification logic
# ---------------------------------------------------------------------------
SDF_THRESHOLDS = {
    "user_count": 10_000_000,       # 1 crore users
    "sensitive_data_volume": 100_000,
    "annual_turnover_crore": 500,
}

SECTOR_SENSITIVE = {SectorType.HEALTH, SectorType.FINANCE, SectorType.TELECOM}

ROLE_OBLIGATIONS: dict[DPDPRole, list[str]] = {
    DPDPRole.DATA_FIDUCIARY: [
        "DPDP §6: Obtain valid consent before processing",
        "DPDP §8: Ensure data accuracy",
        "DPDP §9: Additional safeguards for child data",
        "DPDP §10: Appoint Data Protection Officer (if SDF)",
        "DPDP §11: Respond to rights requests within 30 days",
        "DPDP §13: Honor consent withdrawal promptly",
    ],
    DPDPRole.DATA_PROCESSOR: [
        "DPDP §8(3): Process only per fiduciary instructions",
        "DPDP §8(5): Notify fiduciary of any breach",
        "Maintain processing records",
    ],
    DPDPRole.SIGNIFICANT_DATA_FIDUCIARY: [
        "All Data Fiduciary obligations",
        "DPDP §10(2): Appoint Data Protection Officer",
        "DPDP §10(3): Appoint independent data auditor",
        "Conduct annual Data Protection Impact Assessments",
        "Periodic algorithmic accountability reports",
        "Cross-border transfer restrictions apply",
    ],
    DPDPRole.EXEMPT: [
        "Verify exemption basis under Schedule II",
        "Maintain exemption documentation",
    ],
}


def classify(req: ClassifyRequest) -> ClassifyResponse:
    import uuid

    sdf_triggers = []

    if req.is_data_processor_only:
        role = DPDPRole.DATA_PROCESSOR
        is_sdf = False
    elif req.is_govt_entity:
        role = DPDPRole.EXEMPT
        is_sdf = False
    else:
        role = DPDPRole.DATA_FIDUCIARY
        is_sdf = False

        if req.user_count >= SDF_THRESHOLDS["user_count"]:
            sdf_triggers.append(f"User count ≥ 1 crore ({req.user_count:,})")

        if req.processes_child_data:
            sdf_triggers.append("Processes children's personal data (DPDP §9)")

        if req.sector in SECTOR_SENSITIVE and req.processes_sensitive_data:
            sdf_triggers.append(f"Sensitive data in regulated sector: {req.sector.value}")

        if req.ai_ml_profiling:
            sdf_triggers.append("AI/ML profiling of data principals")

        if req.annual_turnover_crore >= SDF_THRESHOLDS["annual_turnover_crore"]:
            sdf_triggers.append(f"Annual turnover ≥ ₹500 Cr ({req.annual_turnover_crore:.0f} Cr)")

        if sdf_triggers:
            role = DPDPRole.SIGNIFICANT_DATA_FIDUCIARY
            is_sdf = True

    # Risk score: weighted sum of risk factors
    risk = 0
    risk += min(40, int(req.user_count / 1_000_000) * 4)
    risk += 20 if req.processes_child_data else 0
    risk += 15 if req.processes_sensitive_data else 0
    risk += 10 if req.ai_ml_profiling else 0
    risk += 10 if req.cross_border_transfers else 0
    risk += 5  if req.sector in SECTOR_SENSITIVE else 0
    risk = min(100, risk)

    CLASSIFICATIONS.labels(role=role.value, is_sdf=str(is_sdf)).inc()
    log.info("entity.classified", entity_id=req.entity_id, role=role, is_sdf=is_sdf, risk=risk)

    return ClassifyResponse(
        entity_id=req.entity_id,
        role=role,
        is_sdf=is_sdf,
        sdf_triggers=sdf_triggers,
        obligations=ROLE_OBLIGATIONS[role],
        risk_score=risk,
        classification_id=str(uuid.uuid4()),
        classified_at=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "service": "role-classifier"}


@app.post("/classify", response_model=ClassifyResponse)
async def classify_entity(req: ClassifyRequest):
    """Classify an entity's DPDP role and SDF status."""
    return classify(req)


@app.post("/classify/batch")
async def classify_batch(requests: list[ClassifyRequest]):
    """Batch classification for bulk onboarding."""
    if len(requests) > 100:
        raise HTTPException(status_code=422, detail="Batch size must be ≤ 100")
    return [classify(r) for r in requests]


@app.get("/obligations/{role}")
async def get_obligations(role: DPDPRole):
    """Return DPDP obligations for a given role."""
    return {"role": role, "obligations": ROLE_OBLIGATIONS.get(role, [])}


@app.get("/sdf-thresholds")
async def sdf_thresholds():
    """Return current SDF determination thresholds."""
    return SDF_THRESHOLDS
