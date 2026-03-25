"""
Shadow AI Discovery — DPDP Compliance OS  Day 8
Detects rogue / unsanctioned AI systems processing personal data
by analysing Kafka event streams, API traffic patterns, and
network flow metadata. Generates incident alerts for the DPO console.
"""

import uuid
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import structlog
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import Counter, Gauge, make_asgi_app
from pydantic import BaseModel, Field

log = structlog.get_logger()

app = FastAPI(title="Shadow AI Discovery", version="1.0.0",
              description="Detect and alert on unsanctioned AI systems processing personal data")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/metrics", make_asgi_app())
FastAPIInstrumentor.instrument_app(app)

SHADOW_SYSTEMS_DETECTED = Counter("shadow_ai_detected_total", "Shadow AI systems detected", ["risk_level"])
ACTIVE_ALERTS           = Gauge("shadow_ai_active_alerts", "Currently open shadow AI alerts")


# ---------------------------------------------------------------------------
# Known AI system signatures (expanded in production via threat intel feed)
# ---------------------------------------------------------------------------
AI_API_SIGNATURES: dict[str, dict] = {
    r"api\.openai\.com":          {"name": "OpenAI GPT", "data_risk": "high",    "sends_pii": True},
    r"generativelanguage\.google": {"name": "Google Gemini", "data_risk": "high", "sends_pii": True},
    r"api\.anthropic\.com":       {"name": "Anthropic Claude", "data_risk": "high","sends_pii": True},
    r"api\.cohere\.com":          {"name": "Cohere AI", "data_risk": "medium",   "sends_pii": True},
    r"huggingface\.co/api":       {"name": "HuggingFace Inference", "data_risk": "medium", "sends_pii": False},
    r"replicate\.com/v1":         {"name": "Replicate", "data_risk": "medium",   "sends_pii": False},
    r"\.amazonaws\.com/bedrock":  {"name": "AWS Bedrock", "data_risk": "high",   "sends_pii": True},
    r"aiplatform\.googleapis\.com": {"name": "GCP Vertex AI", "data_risk": "high", "sends_pii": True},
}

SUSPICIOUS_PAYLOAD_PATTERNS = [
    r"\b\d{10,12}\b",           # Phone numbers (Indian format)
    r"\b[A-Z]{5}\d{4}[A-Z]\b",  # PAN card
    r"\b\d{12}\b",               # Aadhaar
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",  # Email
]


class RiskLevel(str, Enum):
    INFO     = "info"
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


class AlertStatus(str, Enum):
    OPEN        = "open"
    UNDER_REVIEW = "under_review"
    SANCTIONED  = "sanctioned"   # DPO approved retroactively
    MITIGATED   = "mitigated"
    FALSE_POSITIVE = "false_positive"


class NetworkFlowEvent(BaseModel):
    event_id: Optional[str] = None
    source_service: str
    source_ip: str
    destination_url: str
    http_method: str = "POST"
    payload_sample: Optional[str] = None   # First 500 chars only, pre-sanitised
    bytes_sent: int = 0
    timestamp: Optional[str] = None
    detected_by: str = "network_sensor"


class ShadowAIAlert(BaseModel):
    alert_id: str
    detected_system: str
    source_service: str
    destination_url: str
    risk_level: RiskLevel
    pii_exposure_likely: bool
    pii_patterns_found: list[str]
    compliance_violations: list[str]
    required_actions: list[str]
    status: AlertStatus
    detected_at: str
    first_seen: str
    event_count: int


class ScanRequest(BaseModel):
    scan_id: Optional[str] = None
    network_events: list[NetworkFlowEvent]
    sanctioned_ai_ids: list[str] = []


class ScanReport(BaseModel):
    scan_id: str
    events_processed: int
    alerts_raised: int
    new_alerts: list[ShadowAIAlert]
    known_shadow_systems: int
    scan_duration_ms: float
    scanned_at: str


# ---------------------------------------------------------------------------
# Alert store
# ---------------------------------------------------------------------------
_alerts: dict[str, dict] = {}   # alert_id → alert
_system_first_seen: dict[str, str] = {}


def detect_shadow_ai(event: NetworkFlowEvent, sanctioned: list[str]) -> Optional[ShadowAIAlert]:
    url = event.destination_url.lower()
    matched_sig: Optional[dict] = None
    matched_name: Optional[str] = None

    for pattern, sig in AI_API_SIGNATURES.items():
        if re.search(pattern, url, re.IGNORECASE):
            matched_sig = sig
            matched_name = sig["name"]
            break

    if not matched_sig:
        return None

    # Check if this AI system is already sanctioned by DPO
    system_key = re.sub(r"https?://|/.*", "", url)
    if system_key in sanctioned:
        return None

    # PII detection in payload
    pii_found: list[str] = []
    if event.payload_sample:
        for pattern in SUSPICIOUS_PAYLOAD_PATTERNS:
            if re.search(pattern, event.payload_sample, re.IGNORECASE):
                pii_found.append(pattern)

    risk = RiskLevel.MEDIUM
    if matched_sig.get("sends_pii") and pii_found:
        risk = RiskLevel.CRITICAL
    elif matched_sig.get("sends_pii"):
        risk = RiskLevel.HIGH
    elif pii_found:
        risk = RiskLevel.HIGH

    violations = [
        "Unsanctioned AI system processing data without DPO approval",
        "DPDP §6: No consent covers AI processing via external service",
    ]
    if pii_found:
        violations.append("Personal data transmitted to external AI — potential DPDP §16 cross-border violation")
    if matched_sig.get("data_risk") == "high":
        violations.append("High-risk AI provider — DPIA required before use (DPDP §10)")

    required_actions = [
        "Immediately block outbound traffic to this endpoint",
        "Identify team/developer responsible",
        "Conduct retroactive DPIA",
        "DPO decision: sanction or decommission within 72 hours",
    ]
    if pii_found:
        required_actions.insert(0, "URGENT: Personal data may have been transmitted — initiate breach assessment")

    now = datetime.now(timezone.utc).isoformat()
    first_seen = _system_first_seen.setdefault(system_key, now)
    existing = next((a for a in _alerts.values() if a["destination_url"] == event.destination_url and a["status"] == AlertStatus.OPEN.value), None)

    if existing:
        existing["event_count"] += 1
        return None   # Already alerted

    alert_id = str(uuid.uuid4())
    alert = ShadowAIAlert(
        alert_id=alert_id,
        detected_system=matched_name,
        source_service=event.source_service,
        destination_url=event.destination_url,
        risk_level=risk,
        pii_exposure_likely=bool(pii_found),
        pii_patterns_found=pii_found,
        compliance_violations=violations,
        required_actions=required_actions,
        status=AlertStatus.OPEN,
        detected_at=now,
        first_seen=first_seen,
        event_count=1,
    )
    _alerts[alert_id] = {**alert.model_dump()}
    SHADOW_SYSTEMS_DETECTED.labels(risk_level=risk.value).inc()
    ACTIVE_ALERTS.inc()
    log.warning("shadow_ai.detected", alert_id=alert_id, system=matched_name, risk=risk.value, pii=bool(pii_found))
    return alert


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "service": "shadow-ai-discovery", "active_alerts": len([a for a in _alerts.values() if a["status"] == "open"])}

@app.post("/shadow-ai/scan", response_model=ScanReport)
async def scan(req: ScanRequest):
    """Process a batch of network flow events and detect shadow AI usage."""
    import time
    t0 = time.monotonic()
    scan_id = req.scan_id or str(uuid.uuid4())
    new_alerts: list[ShadowAIAlert] = []

    for event in req.network_events:
        if not event.timestamp:
            event.timestamp = datetime.now(timezone.utc).isoformat()
        alert = detect_shadow_ai(event, req.sanctioned_ai_ids)
        if alert:
            new_alerts.append(alert)

    elapsed_ms = round((time.monotonic() - t0) * 1000, 2)
    log.info("shadow_ai.scan.complete", scan_id=scan_id, events=len(req.network_events), alerts=len(new_alerts))

    return ScanReport(
        scan_id=scan_id,
        events_processed=len(req.network_events),
        alerts_raised=len(new_alerts),
        new_alerts=new_alerts,
        known_shadow_systems=len(_system_first_seen),
        scan_duration_ms=elapsed_ms,
        scanned_at=datetime.now(timezone.utc).isoformat(),
    )

@app.get("/shadow-ai/alerts")
async def list_alerts(status: Optional[AlertStatus] = None, risk: Optional[RiskLevel] = None):
    alerts = list(_alerts.values())
    if status:
        alerts = [a for a in alerts if a["status"] == status.value]
    if risk:
        alerts = [a for a in alerts if a["risk_level"] == risk.value]
    return {"alerts": alerts, "count": len(alerts)}

@app.post("/shadow-ai/alerts/{alert_id}/sanction")
async def sanction_system(alert_id: str, dpo_id: str, justification: str):
    alert = _alerts.get(alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    alert["status"] = AlertStatus.SANCTIONED.value
    alert["sanctioned_by"] = dpo_id
    alert["justification"] = justification
    ACTIVE_ALERTS.dec()
    log.info("shadow_ai.sanctioned", alert_id=alert_id, dpo=dpo_id)
    return {"alert_id": alert_id, "status": "sanctioned"}

@app.get("/shadow-ai/signatures")
async def list_signatures():
    return {"signatures": {k: v for k, v in AI_API_SIGNATURES.items()}, "count": len(AI_API_SIGNATURES)}
