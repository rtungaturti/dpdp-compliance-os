"""Domain models for the Consent Engine."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class LegalBasis(str, Enum):
    CONSENT = "consent"
    LEGITIMATE_INTEREST = "legitimate_interest"   # DPDP §7 — deemed consent
    LEGAL_OBLIGATION = "legal_obligation"
    VITAL_INTERESTS = "vital_interests"
    PUBLIC_TASK = "public_task"


class ConsentStatus(str, Enum):
    ACTIVE = "active"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"
    PENDING = "pending"


class ConsentRecord(BaseModel):
    consent_id: str
    principal_id: str
    data_fiduciary_id: str
    purpose_ids: list[str]
    legal_basis: LegalBasis
    data_categories: list[str]
    retention_days: int
    is_child: bool = False
    guardian_consent_ref: Optional[str] = None
    status: ConsentStatus
    granted_at: Optional[datetime] = None
    withdrawn_at: Optional[datetime] = None
    metadata: dict = {}

    def to_response(self) -> dict:
        return {
            "consent_id": self.consent_id,
            "principal_id": self.principal_id,
            "status": self.status,
            "granted_at": self.granted_at.isoformat() if self.granted_at else None,
            "withdrawn_at": self.withdrawn_at.isoformat() if self.withdrawn_at else None,
            "purposes": self.purpose_ids,
            "legal_basis": self.legal_basis,
            "data_fiduciary_id": self.data_fiduciary_id,
        }
