"""
PBAC Engine — DPDP Compliance OS  Day 7
Purpose-Based Access Control: every data access request is evaluated
against the consented purposes, DPDP role, and current compliance state.
Acts as a policy enforcement point for all downstream services.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import Counter, Histogram, make_asgi_app
from pydantic import BaseModel, Field

log = structlog.get_logger()

app = FastAPI(title="PBAC Engine", version="1.0.0",
              description="Purpose-Based Access Control — DPDP §6 enforcement at the data layer")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/metrics", make_asgi_app())
FastAPIInstrumentor.instrument_app(app)

ACCESS_ALLOWED  = Counter("pbac_access_allowed_total",  "Access decisions: allowed",  ["purpose", "role"])
ACCESS_DENIED   = Counter("pbac_access_denied_total",   "Access decisions: denied",   ["reason"])
DECISION_LATENCY = Histogram("pbac_decision_latency_seconds", "PBAC decision latency")


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------
class AccessDecision(str, Enum):
    ALLOW         = "allow"
    DENY          = "deny"
    ALLOW_PARTIAL = "allow_partial"   # Allow but with field-level redaction
    REQUIRE_MFA   = "require_mfa"


class DenialReason(str, Enum):
    NO_CONSENT         = "no_consent"
    CONSENT_WITHDRAWN  = "consent_withdrawn"
    PURPOSE_MISMATCH   = "purpose_mismatch"
    ROLE_INSUFFICIENT  = "role_insufficient"
    DATA_EXPIRED       = "data_expired"
    CROSS_BORDER_BLOCK = "cross_border_block"
    CHILD_DATA_GUARD   = "child_data_guard"
    SDF_RESTRICTION    = "sdf_restriction"


class PolicyRule(BaseModel):
    rule_id: str
    name: str
    data_categories: list[str]
    allowed_purposes: list[str]
    allowed_roles: list[str]
    requires_consent: bool = True
    requires_mfa: bool = False
    redact_fields: list[str] = []
    max_records_per_request: Optional[int] = None


class AccessRequest(BaseModel):
    request_id: Optional[str] = None
    principal_id: str
    requestor_id: str
    requestor_role: str
    data_fiduciary_id: str
    requested_purpose: str
    data_categories: list[str]
    data_fields: list[str] = []
    record_count: int = Field(1, ge=1)
    requestor_country: str = "IN"
    is_bulk_export: bool = False


class AccessResponse(BaseModel):
    request_id: str
    decision: AccessDecision
    allowed_fields: list[str]
    redacted_fields: list[str]
    denial_reasons: list[DenialReason]
    denial_detail: Optional[str]
    conditions: list[str]
    audit_id: str
    decided_at: str
    policy_applied: Optional[str]
    requires_mfa: bool


# ---------------------------------------------------------------------------
# Policy store (in production: load from DB / OPA)
# ---------------------------------------------------------------------------
POLICIES: list[PolicyRule] = [
    PolicyRule(
        rule_id="P-001",
        name="Marketing analytics — general data",
        data_categories=["email", "name", "browsing_behavior"],
        allowed_purposes=["marketing", "analytics", "personalisation"],
        allowed_roles=["analyst", "marketing_manager"],
        requires_consent=True,
        max_records_per_request=10000,
    ),
    PolicyRule(
        rule_id="P-002",
        name="Health data — clinical only",
        data_categories=["health", "medical_records", "prescription"],
        allowed_purposes=["clinical_care", "research"],
        allowed_roles=["doctor", "researcher", "nurse"],
        requires_consent=True,
        requires_mfa=True,
        max_records_per_request=100,
    ),
    PolicyRule(
        rule_id="P-003",
        name="Financial data — fraud detection",
        data_categories=["financial", "transaction_history", "credit_score"],
        allowed_purposes=["fraud_detection", "credit_assessment", "legal_compliance"],
        allowed_roles=["risk_analyst", "compliance_officer", "legal"],
        requires_consent=False,  # Deemed consent under DPDP §7(d) — legal obligation
        requires_mfa=True,
    ),
    PolicyRule(
        rule_id="P-004",
        name="Children data — education only",
        data_categories=["children", "student_records"],
        allowed_purposes=["education", "safety"],
        allowed_roles=["teacher", "school_admin"],
        requires_consent=True,
        requires_mfa=True,
        max_records_per_request=50,
        redact_fields=["biometric", "health_condition", "family_details"],
    ),
]

# Simulated consent store (in production: query consent-engine)
_consent_store: dict[str, dict] = {}   # principal_id → {purpose: True/False}


def find_matching_policy(req: AccessRequest) -> Optional[PolicyRule]:
    for policy in POLICIES:
        cat_match = any(c in policy.data_categories for c in req.data_categories)
        purpose_match = req.requested_purpose in policy.allowed_purposes
        if cat_match and purpose_match:
            return policy
    return None


def evaluate_access(req: AccessRequest) -> AccessResponse:
    import time
    t0 = time.monotonic()

    request_id = req.request_id or str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    denial_reasons: list[DenialReason] = []
    conditions: list[str] = []
    redacted: list[str] = []

    # Find matching policy
    policy = find_matching_policy(req)
    if not policy:
        denial_reasons.append(DenialReason.PURPOSE_MISMATCH)
        decision = AccessDecision.DENY
        log.warning("pbac.denied", request_id=request_id, reason="no_policy_match", purpose=req.requested_purpose)
        ACCESS_DENIED.labels(reason=DenialReason.PURPOSE_MISMATCH.value).inc()
        return AccessResponse(
            request_id=request_id, decision=decision,
            allowed_fields=[], redacted_fields=[], denial_reasons=denial_reasons,
            denial_detail=f"No policy permits '{req.requested_purpose}' access to {req.data_categories}",
            conditions=[], audit_id=str(uuid.uuid4()), decided_at=now.isoformat(),
            policy_applied=None, requires_mfa=False,
        )

    # Role check
    if req.requestor_role not in policy.allowed_roles:
        denial_reasons.append(DenialReason.ROLE_INSUFFICIENT)

    # Consent check (simulated — in production: call consent-engine /check)
    if policy.requires_consent:
        consent_key = f"{req.principal_id}:{req.data_fiduciary_id}:{req.requested_purpose}"
        has_consent = _consent_store.get(consent_key, {}).get("active", False)
        if not has_consent:
            denial_reasons.append(DenialReason.NO_CONSENT)

    # Children data extra guard
    if "children" in req.data_categories and req.is_bulk_export:
        denial_reasons.append(DenialReason.CHILD_DATA_GUARD)
        conditions.append("Children's data bulk export requires DPO written approval")

    # Volume check
    if policy.max_records_per_request and req.record_count > policy.max_records_per_request:
        denial_reasons.append(DenialReason.SDF_RESTRICTION)
        conditions.append(f"Request exceeds policy limit of {policy.max_records_per_request} records")

    # MFA requirement
    requires_mfa = policy.requires_mfa

    # Decide
    if denial_reasons:
        decision = AccessDecision.DENY
        for r in denial_reasons:
            ACCESS_DENIED.labels(reason=r.value).inc()
        log.warning("pbac.denied", request_id=request_id, reasons=[r.value for r in denial_reasons])
    elif policy.redact_fields:
        decision = AccessDecision.ALLOW_PARTIAL
        redacted = [f for f in req.data_fields if f in policy.redact_fields]
        ACCESS_ALLOWED.labels(purpose=req.requested_purpose, role=req.requestor_role).inc()
    elif requires_mfa:
        decision = AccessDecision.REQUIRE_MFA
        ACCESS_ALLOWED.labels(purpose=req.requested_purpose, role=req.requestor_role).inc()
    else:
        decision = AccessDecision.ALLOW
        ACCESS_ALLOWED.labels(purpose=req.requested_purpose, role=req.requestor_role).inc()

    allowed_fields = [f for f in req.data_fields if f not in redacted] if decision != AccessDecision.DENY else []

    DECISION_LATENCY.observe(time.monotonic() - t0)
    log.info("pbac.decision", request_id=request_id, decision=decision.value, policy=policy.rule_id)

    return AccessResponse(
        request_id=request_id,
        decision=decision,
        allowed_fields=allowed_fields,
        redacted_fields=redacted,
        denial_reasons=denial_reasons,
        denial_detail=None if not denial_reasons else f"Access denied: {', '.join(r.value for r in denial_reasons)}",
        conditions=conditions,
        audit_id=str(uuid.uuid4()),
        decided_at=now.isoformat(),
        policy_applied=policy.rule_id if policy else None,
        requires_mfa=requires_mfa,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "service": "pbac-engine", "policies_loaded": len(POLICIES)}

@app.post("/pbac/authorize", response_model=AccessResponse)
async def authorize(req: AccessRequest):
    """Evaluate an access request against DPDP-aligned PBAC policies."""
    return evaluate_access(req)

@app.post("/pbac/authorize/bulk")
async def authorize_bulk(requests: list[AccessRequest]):
    if len(requests) > 100:
        raise HTTPException(422, "Bulk limit: 100 requests")
    return [evaluate_access(r) for r in requests]

@app.get("/pbac/policies")
async def list_policies():
    return {"policies": POLICIES, "count": len(POLICIES)}

@app.post("/pbac/policies", status_code=201)
async def create_policy(policy: PolicyRule):
    if any(p.rule_id == policy.rule_id for p in POLICIES):
        raise HTTPException(409, f"Policy {policy.rule_id} already exists")
    POLICIES.append(policy)
    log.info("pbac.policy.created", rule_id=policy.rule_id)
    return {"rule_id": policy.rule_id, "status": "created"}

# Consent simulation endpoint (in production, PBAC calls consent-engine directly)
@app.post("/pbac/consent/mock")
async def mock_consent(principal_id: str, fiduciary_id: str, purpose: str, active: bool = True):
    key = f"{principal_id}:{fiduciary_id}:{purpose}"
    _consent_store[key] = {"active": active, "set_at": datetime.now(timezone.utc).isoformat()}
    return {"key": key, "active": active}
