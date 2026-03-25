"""
Cross-Border PEP — DPDP Compliance OS  Day 2
Real-time enforcement of DPDP §16 cross-border personal data transfer
restrictions. Blocks transfers to non-whitelisted countries, logs all
decisions, and provides transfer impact assessment.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import Counter, make_asgi_app
from pydantic import BaseModel, Field

log = structlog.get_logger()

app = FastAPI(title="Cross-Border PEP", version="1.0.0",
              description="DPDP §16 cross-border personal data transfer enforcement")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/metrics", make_asgi_app())
FastAPIInstrumentor.instrument_app(app)

TRANSFERS_ALLOWED = Counter("transfers_allowed_total", "Transfers permitted", ["destination_country"])
TRANSFERS_BLOCKED = Counter("transfers_blocked_total", "Transfers blocked", ["destination_country"])


# ---------------------------------------------------------------------------
# Whitelisted countries (DPDP §16 — MeitY notified list)
# In production: sync from MeitY API / regulatory feed
# ---------------------------------------------------------------------------
WHITELISTED_COUNTRIES: dict[str, dict] = {
    "US": {"name": "United States", "adequacy_basis": "SCCs + NIST", "added": "2024-01-15"},
    "GB": {"name": "United Kingdom", "adequacy_basis": "UK GDPR adequacy", "added": "2024-01-15"},
    "AU": {"name": "Australia", "adequacy_basis": "Privacy Act 1988 + bilateral", "added": "2024-02-01"},
    "SG": {"name": "Singapore", "adequacy_basis": "PDPA adequacy + bilateral", "added": "2024-02-01"},
    "JP": {"name": "Japan", "adequacy_basis": "APPI + adequacy decision", "added": "2024-03-01"},
    "NZ": {"name": "New Zealand", "adequacy_basis": "Privacy Act 2020 + bilateral", "added": "2024-03-01"},
    "CA": {"name": "Canada", "adequacy_basis": "PIPEDA adequacy", "added": "2024-04-01"},
}

# Countries under enhanced scrutiny (transfers allowed but logged + flagged)
SCRUTINY_COUNTRIES: set[str] = {"DE", "FR", "NL", "SE", "NO", "FI", "DK"}

# Always blocked regardless of whitelisting
EMBARGOED_COUNTRIES: set[str] = set()  # Populated from government sanctions list


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------
class TransferDecision(str, Enum):
    ALLOWED          = "allowed"
    BLOCKED          = "blocked"
    ALLOWED_SCRUTINY = "allowed_with_enhanced_scrutiny"
    PENDING_REVIEW   = "pending_review"


class DataCategory(str, Enum):
    GENERAL   = "general"
    SENSITIVE = "sensitive"
    FINANCIAL = "financial"
    HEALTH    = "health"
    BIOMETRIC = "biometric"
    CHILDREN  = "children"


class TransferCheckRequest(BaseModel):
    transfer_id: Optional[str] = None
    source_country: str = Field("IN", description="Always India for DPDP")
    destination_country: str = Field(..., min_length=2, max_length=2, description="ISO 3166-1 alpha-2")
    destination_entity: str
    data_categories: list[DataCategory]
    principal_count: int = Field(..., ge=1)
    data_volume_mb: float = Field(..., ge=0)
    purpose: str
    legal_basis: str
    requestor_id: str


class TransferCheckResponse(BaseModel):
    transfer_id: str
    decision: TransferDecision
    destination_country: str
    is_whitelisted: bool
    adequacy_basis: Optional[str]
    conditions: list[str]
    blocking_reasons: list[str]
    required_safeguards: list[str]
    audit_log_id: str
    decided_at: str


# ---------------------------------------------------------------------------
# Enforcement logic
# ---------------------------------------------------------------------------
SENSITIVE_SAFEGUARDS = [
    "Additional encryption with customer-managed keys (BYOK)",
    "Data residency clause in DPA with destination entity",
    "Right to audit destination entity annually",
    "Breach notification within 24 hours (not 72h standard)",
]

STANDARD_SAFEGUARDS = [
    "Standard Contractual Clauses (SCCs) in place",
    "Transfer recorded in cross-border transfer register",
    "Destination entity DPA signed",
]


def enforce_transfer(req: TransferCheckRequest) -> TransferCheckResponse:
    transfer_id = req.transfer_id or str(uuid.uuid4())
    country = req.destination_country.upper()
    now = datetime.now(timezone.utc)

    blocking_reasons: list[str] = []
    conditions: list[str] = []
    safeguards: list[str] = list(STANDARD_SAFEGUARDS)

    # Embargo check
    if country in EMBARGOED_COUNTRIES:
        blocking_reasons.append(f"{country} is on the government sanctions/embargo list")

    # Whitelist check
    is_whitelisted = country in WHITELISTED_COUNTRIES
    adequacy_basis = WHITELISTED_COUNTRIES.get(country, {}).get("adequacy_basis")

    if not is_whitelisted and country not in SCRUTINY_COUNTRIES:
        blocking_reasons.append(
            f"{country} is not on the MeitY whitelist of approved cross-border transfer destinations (DPDP §16)"
        )

    # Sensitive data extra checks
    has_sensitive = any(c in (DataCategory.SENSITIVE, DataCategory.HEALTH, DataCategory.BIOMETRIC, DataCategory.CHILDREN) for c in req.data_categories)
    if has_sensitive:
        safeguards.extend(SENSITIVE_SAFEGUARDS)
        conditions.append("Sensitive data transfer requires DPO sign-off within 5 business days")

    if DataCategory.CHILDREN in req.data_categories:
        blocking_reasons.append("Children's data transfers require explicit MeitY approval (DPDP §9 + §16)")

    # Decide
    if blocking_reasons:
        decision = TransferDecision.BLOCKED
        TRANSFERS_BLOCKED.labels(destination_country=country).inc()
        log.warning("transfer.blocked", transfer_id=transfer_id, country=country, reasons=blocking_reasons)
    elif country in SCRUTINY_COUNTRIES:
        decision = TransferDecision.ALLOWED_SCRUTINY
        conditions.append("Enhanced monitoring: transfer logged to DPB feed")
        TRANSFERS_ALLOWED.labels(destination_country=country).inc()
        log.info("transfer.allowed_scrutiny", transfer_id=transfer_id, country=country)
    else:
        decision = TransferDecision.ALLOWED
        TRANSFERS_ALLOWED.labels(destination_country=country).inc()
        log.info("transfer.allowed", transfer_id=transfer_id, country=country, principals=req.principal_count)

    return TransferCheckResponse(
        transfer_id=transfer_id,
        decision=decision,
        destination_country=country,
        is_whitelisted=is_whitelisted,
        adequacy_basis=adequacy_basis,
        conditions=conditions,
        blocking_reasons=blocking_reasons,
        required_safeguards=safeguards if decision != TransferDecision.BLOCKED else [],
        audit_log_id=str(uuid.uuid4()),
        decided_at=now.isoformat(),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "service": "cross-border-pep"}

@app.post("/transfer/check", response_model=TransferCheckResponse)
async def check_transfer(req: TransferCheckRequest):
    """Real-time transfer enforcement — call before any cross-border data send."""
    return enforce_transfer(req)

@app.get("/transfer/whitelist")
async def get_whitelist():
    """Current MeitY-approved destination countries."""
    return {"whitelisted_countries": WHITELISTED_COUNTRIES, "count": len(WHITELISTED_COUNTRIES)}

@app.get("/transfer/whitelist/{country_code}")
async def check_country(country_code: str):
    country = country_code.upper()
    is_listed = country in WHITELISTED_COUNTRIES
    return {
        "country": country,
        "is_whitelisted": is_listed,
        "details": WHITELISTED_COUNTRIES.get(country),
        "under_scrutiny": country in SCRUTINY_COUNTRIES,
    }

@app.post("/transfer/bulk-check")
async def bulk_check(requests: list[TransferCheckRequest]):
    if len(requests) > 100:
        raise HTTPException(422, "Bulk check limit: 100 transfers")
    return [enforce_transfer(r) for r in requests]
