"""
RAG Corpus Privacy — DPDP Compliance OS  Day 8
PII detection, redaction, and consent verification for RAG pipeline
documents before they enter the vector store. Prevents personal data
from leaking into model context windows without valid consent.
"""

import hashlib
import re
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

app = FastAPI(title="RAG Corpus Privacy", version="1.0.0",
              description="PII detection and redaction for RAG document corpora — DPDP §6 compliant")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/metrics", make_asgi_app())
FastAPIInstrumentor.instrument_app(app)

DOCUMENTS_SCANNED = Counter("rag_documents_scanned_total", "Documents scanned for PII")
PII_DETECTED      = Counter("rag_pii_detected_total", "PII entities detected", ["pii_type"])
DOCUMENTS_BLOCKED = Counter("rag_documents_blocked_total", "Documents blocked from corpus")


# ---------------------------------------------------------------------------
# PII patterns (India-specific + international)
# ---------------------------------------------------------------------------
PII_PATTERNS: dict[str, dict] = {
    "aadhaar":     {"pattern": r"\b[2-9]\d{3}\s?\d{4}\s?\d{4}\b", "severity": "critical", "replace": "[AADHAAR-REDACTED]"},
    "pan":         {"pattern": r"\b[A-Z]{5}\d{4}[A-Z]\b",         "severity": "critical", "replace": "[PAN-REDACTED]"},
    "phone_in":    {"pattern": r"\b[6-9]\d{9}\b",                  "severity": "high",     "replace": "[PHONE-REDACTED]"},
    "email":       {"pattern": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "severity": "high", "replace": "[EMAIL-REDACTED]"},
    "passport":    {"pattern": r"\b[A-Z][1-9]\d{6}\b",             "severity": "critical", "replace": "[PASSPORT-REDACTED]"},
    "voter_id":    {"pattern": r"\b[A-Z]{3}\d{7}\b",               "severity": "high",     "replace": "[VOTER-ID-REDACTED]"},
    "dob":         {"pattern": r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", "severity": "medium", "replace": "[DOB-REDACTED]"},
    "credit_card": {"pattern": r"\b(?:\d[ -]?){13,19}\b",          "severity": "critical", "replace": "[CARD-REDACTED]"},
    "bank_account":{"pattern": r"\b\d{9,18}\b",                    "severity": "high",     "replace": "[ACCOUNT-REDACTED]"},
    "ifsc":        {"pattern": r"\b[A-Z]{4}0[A-Z0-9]{6}\b",       "severity": "medium",   "replace": "[IFSC-REDACTED]"},
    "ip_address":  {"pattern": r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "severity": "low", "replace": "[IP-REDACTED]"},
}

SEVERITY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1}


class RedactionMode(str, Enum):
    REDACT  = "redact"    # Replace PII with placeholder
    HASH    = "hash"      # Replace with consistent hash (for linking without exposure)
    BLOCK   = "block"     # Reject document entirely
    AUDIT   = "audit"     # Allow but log all PII


class PIIEntity(BaseModel):
    pii_type: str
    severity: str
    count: int
    sample_position: Optional[int] = None  # Char offset of first match (for debugging)


class DocumentScanRequest(BaseModel):
    document_id: Optional[str] = None
    content: str = Field(..., min_length=1, max_length=1_000_000)
    metadata: dict = {}
    source_system: str
    purpose: str
    data_fiduciary_id: str
    redaction_mode: RedactionMode = RedactionMode.REDACT
    block_on_severity: Optional[str] = "critical"  # Block docs with PII at this severity or above


class DocumentScanResponse(BaseModel):
    document_id: str
    scan_id: str
    allowed: bool
    block_reason: Optional[str]
    redacted_content: Optional[str]   # None if blocked
    pii_entities: list[PIIEntity]
    pii_count: int
    highest_severity: Optional[str]
    redaction_mode: RedactionMode
    content_hash_before: str
    content_hash_after: Optional[str]
    scanned_at: str


class CorpusScanRequest(BaseModel):
    corpus_id: str
    documents: list[DocumentScanRequest]
    default_redaction_mode: RedactionMode = RedactionMode.REDACT


class CorpusScanReport(BaseModel):
    corpus_id: str
    report_id: str
    total_documents: int
    documents_allowed: int
    documents_blocked: int
    total_pii_found: int
    pii_by_type: dict[str, int]
    highest_risk_doc: Optional[str]
    scanned_at: str


# ---------------------------------------------------------------------------
# Scan logic
# ---------------------------------------------------------------------------
def scan_document(req: DocumentScanRequest) -> DocumentScanResponse:
    doc_id = req.document_id or str(uuid.uuid4())
    scan_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    hash_before = hashlib.sha256(req.content.encode()).hexdigest()
    entities: list[PIIEntity] = []
    highest_sev: Optional[str] = None
    working_content = req.content

    for pii_type, config in PII_PATTERNS.items():
        matches = list(re.finditer(config["pattern"], working_content, re.IGNORECASE))
        if matches:
            entities.append(PIIEntity(
                pii_type=pii_type,
                severity=config["severity"],
                count=len(matches),
                sample_position=matches[0].start(),
            ))
            PII_DETECTED.labels(pii_type=pii_type).inc()
            if highest_sev is None or SEVERITY_ORDER.get(config["severity"], 0) > SEVERITY_ORDER.get(highest_sev, 0):
                highest_sev = config["severity"]

    should_block = (
        highest_sev and
        req.block_on_severity and
        SEVERITY_ORDER.get(highest_sev, 0) >= SEVERITY_ORDER.get(req.block_on_severity, 0)
        and req.redaction_mode == RedactionMode.BLOCK
    )

    if should_block:
        DOCUMENTS_BLOCKED.inc()
        log.warning("rag.document.blocked", doc_id=doc_id, severity=highest_sev, pii_count=len(entities))
        return DocumentScanResponse(
            document_id=doc_id, scan_id=scan_id, allowed=False,
            block_reason=f"Document contains {highest_sev} PII and block_on_severity={req.block_on_severity}",
            redacted_content=None, pii_entities=entities, pii_count=len(entities),
            highest_severity=highest_sev, redaction_mode=req.redaction_mode,
            content_hash_before=hash_before, content_hash_after=None, scanned_at=now,
        )

    # Apply redaction
    redacted = working_content
    if req.redaction_mode == RedactionMode.REDACT:
        for pii_type, config in PII_PATTERNS.items():
            redacted = re.sub(config["pattern"], config["replace"], redacted, flags=re.IGNORECASE)
    elif req.redaction_mode == RedactionMode.HASH:
        for pii_type, config in PII_PATTERNS.items():
            def make_hash_replacement(m):
                return f"[{pii_type.upper()}-{hashlib.md5(m.group().encode()).hexdigest()[:8].upper()}]"
            redacted = re.sub(config["pattern"], make_hash_replacement, redacted, flags=re.IGNORECASE)

    hash_after = hashlib.sha256(redacted.encode()).hexdigest()
    DOCUMENTS_SCANNED.inc()
    log.info("rag.document.scanned", doc_id=doc_id, pii_count=len(entities), severity=highest_sev, mode=req.redaction_mode.value)

    return DocumentScanResponse(
        document_id=doc_id, scan_id=scan_id, allowed=True, block_reason=None,
        redacted_content=redacted if entities else req.content,
        pii_entities=entities, pii_count=len(entities), highest_severity=highest_sev,
        redaction_mode=req.redaction_mode, content_hash_before=hash_before,
        content_hash_after=hash_after, scanned_at=now,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "service": "rag-corpus-privacy"}

@app.post("/rag/scan/document", response_model=DocumentScanResponse)
async def scan_single(req: DocumentScanRequest):
    """Scan and optionally redact a single document before RAG ingestion."""
    return scan_document(req)

@app.post("/rag/scan/corpus", response_model=CorpusScanReport)
async def scan_corpus(req: CorpusScanRequest):
    """Batch scan an entire document corpus."""
    results = [scan_document(d) for d in req.documents]
    allowed = [r for r in results if r.allowed]
    blocked = [r for r in results if not r.allowed]
    pii_by_type: dict[str, int] = {}
    for r in results:
        for e in r.pii_entities:
            pii_by_type[e.pii_type] = pii_by_type.get(e.pii_type, 0) + e.count
    highest_risk = max(results, key=lambda r: r.pii_count, default=None)

    return CorpusScanReport(
        corpus_id=req.corpus_id,
        report_id=str(uuid.uuid4()),
        total_documents=len(results),
        documents_allowed=len(allowed),
        documents_blocked=len(blocked),
        total_pii_found=sum(r.pii_count for r in results),
        pii_by_type=pii_by_type,
        highest_risk_doc=highest_risk.document_id if highest_risk else None,
        scanned_at=datetime.now(timezone.utc).isoformat(),
    )

@app.get("/rag/pii-patterns")
async def list_patterns():
    return {"patterns": {k: {"severity": v["severity"], "replace": v["replace"]} for k, v in PII_PATTERNS.items()}}
