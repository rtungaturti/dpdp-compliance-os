"""
Consent Engine — DPDP Compliance OS  Day 1
Handles consent capture, withdrawal, propagation, and audit trail.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated

import structlog
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import Counter, Histogram, make_asgi_app
from pydantic import BaseModel, Field

from config import Settings
from db import get_db, init_db
from events import ConsentEventPublisher
from models import ConsentRecord, ConsentStatus, LegalBasis

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
CONSENT_GRANTS    = Counter("consent_grants_total",    "Consents granted",    ["legal_basis"])
CONSENT_WITHDRAWALS = Counter("consent_withdrawals_total", "Consents withdrawn")
REQUEST_LATENCY   = Histogram("request_latency_seconds", "Request latency", ["endpoint"])

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Consent Engine",
    description="DPDP Art. 6–9 compliant consent lifecycle management",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Prometheus metrics
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

FastAPIInstrumentor.instrument_app(app)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class ConsentGrantRequest(BaseModel):
    principal_id: str = Field(..., description="Data principal identifier")
    data_fiduciary_id: str = Field(..., description="Organisation requesting consent")
    purpose_ids: list[str] = Field(..., min_length=1, description="Specific processing purposes")
    legal_basis: LegalBasis = LegalBasis.CONSENT
    data_categories: list[str] = Field(..., description="Categories of personal data")
    retention_days: int = Field(365, ge=1, le=3650)
    is_child: bool = False
    guardian_consent_ref: str | None = None
    metadata: dict = {}


class ConsentWithdrawRequest(BaseModel):
    principal_id: str
    consent_id: str
    reason: str | None = None


class ConsentStatusResponse(BaseModel):
    consent_id: str
    principal_id: str
    status: ConsentStatus
    granted_at: datetime | None
    withdrawn_at: datetime | None
    purposes: list[str]
    legal_basis: LegalBasis
    data_fiduciary_id: str


class ConsentCheckRequest(BaseModel):
    principal_id: str
    data_fiduciary_id: str
    purpose_id: str


# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup():
    settings = Settings()
    await init_db(settings)
    app.state.publisher = ConsentEventPublisher(settings)
    await app.state.publisher.start()
    log.info("consent_engine.started", version="1.0.0")


@app.on_event("shutdown")
async def shutdown():
    if hasattr(app.state, "publisher"):
        await app.state.publisher.stop()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "service": "consent-engine", "ts": datetime.now(timezone.utc).isoformat()}


@app.post("/consent/grant", status_code=status.HTTP_201_CREATED)
async def grant_consent(
    req: ConsentGrantRequest,
    db=Depends(get_db),
):
    """DPDP §6: Capture free, specific, informed, unconditional consent."""
    # Child data principal guard (DPDP §9)
    if req.is_child and not req.guardian_consent_ref:
        raise HTTPException(
            status_code=422,
            detail="Guardian consent reference required for child data principals (DPDP §9)",
        )

    consent_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    record = ConsentRecord(
        consent_id=consent_id,
        principal_id=req.principal_id,
        data_fiduciary_id=req.data_fiduciary_id,
        purpose_ids=req.purpose_ids,
        legal_basis=req.legal_basis,
        data_categories=req.data_categories,
        retention_days=req.retention_days,
        is_child=req.is_child,
        guardian_consent_ref=req.guardian_consent_ref,
        status=ConsentStatus.ACTIVE,
        granted_at=now,
        metadata=req.metadata,
    )

    await db.save_consent(record)

    # Publish event for downstream propagation
    await app.state.publisher.publish_consent_granted(record)

    CONSENT_GRANTS.labels(legal_basis=req.legal_basis.value).inc()
    log.info(
        "consent.granted",
        consent_id=consent_id,
        principal_id=req.principal_id,
        purposes=req.purpose_ids,
    )

    return {
        "consent_id": consent_id,
        "status": ConsentStatus.ACTIVE,
        "granted_at": now.isoformat(),
        "purposes": req.purpose_ids,
        "message": "Consent recorded. Downstream systems will be notified.",
    }


@app.post("/consent/withdraw")
async def withdraw_consent(
    req: ConsentWithdrawRequest,
    db=Depends(get_db),
):
    """DPDP §13(2): Withdrawal must be as easy as granting consent."""
    record = await db.get_consent(req.consent_id, req.principal_id)
    if not record:
        raise HTTPException(status_code=404, detail="Consent record not found")

    if record.status == ConsentStatus.WITHDRAWN:
        raise HTTPException(status_code=409, detail="Consent already withdrawn")

    now = datetime.now(timezone.utc)
    await db.withdraw_consent(req.consent_id, now, req.reason)

    # Publish withdrawal event — withdrawal-propagator will fan this out
    await app.state.publisher.publish_consent_withdrawn(
        consent_id=req.consent_id,
        principal_id=req.principal_id,
        withdrawn_at=now,
        reason=req.reason,
    )

    CONSENT_WITHDRAWALS.inc()
    log.info("consent.withdrawn", consent_id=req.consent_id, principal_id=req.principal_id)

    return {
        "consent_id": req.consent_id,
        "status": ConsentStatus.WITHDRAWN,
        "withdrawn_at": now.isoformat(),
        "message": "Withdrawal propagated to downstream systems.",
    }


@app.get("/consent/{consent_id}", response_model=ConsentStatusResponse)
async def get_consent_status(consent_id: str, principal_id: str, db=Depends(get_db)):
    record = await db.get_consent(consent_id, principal_id)
    if not record:
        raise HTTPException(status_code=404, detail="Consent record not found")
    return record.to_response()


@app.post("/consent/check")
async def check_consent(req: ConsentCheckRequest, db=Depends(get_db)):
    """Real-time consent check used by PBAC engine and downstream services."""
    is_valid = await db.check_active_consent(
        req.principal_id, req.data_fiduciary_id, req.purpose_id
    )
    return {"allowed": is_valid, "purpose_id": req.purpose_id}


@app.get("/consent/principal/{principal_id}")
async def list_principal_consents(principal_id: str, db=Depends(get_db)):
    """Returns all consent records for a given data principal."""
    records = await db.list_consents_for_principal(principal_id)
    return {"principal_id": principal_id, "consents": [r.to_response() for r in records]}


@app.get("/consent/fiduciary/{fiduciary_id}/stats")
async def fiduciary_consent_stats(fiduciary_id: str, db=Depends(get_db)):
    """DPO dashboard: aggregate stats per data fiduciary."""
    stats = await db.get_fiduciary_stats(fiduciary_id)
    return stats
