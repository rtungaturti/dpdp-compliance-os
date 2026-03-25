"""Database layer for Consent Engine - async PostgreSQL via SQLAlchemy."""

import json
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from config import Settings
from models import ConsentRecord, ConsentStatus, LegalBasis

log = structlog.get_logger()

_engine = None
_async_session = None


async def init_db(settings: Settings):
    global _engine, _async_session
    _engine = create_async_engine(
        settings.db_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        echo=False,
    )
    _async_session = sessionmaker(
        _engine, class_=AsyncSession, expire_on_commit=False
    )
    log.info("db.connected", host=settings.db_host, db=settings.db_name)


async def get_db():
    async with _async_session() as session:
        yield ConsentDB(session)


class ConsentDB:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_consent(self, record: ConsentRecord) -> None:
        # Serialize metadata to JSON string - pass as plain $N param,
        # then cast inside the SQL using CAST() not :: (which breaks SQLAlchemy)
        await self.session.execute(
            text("""
                INSERT INTO consent_records (
                    consent_id, principal_id, data_fiduciary_id,
                    purpose_ids, legal_basis, data_categories,
                    retention_days, is_child, guardian_consent_ref,
                    status, granted_at, metadata
                ) VALUES (
                    :consent_id, :principal_id, :data_fiduciary_id,
                    :purpose_ids, :legal_basis, :data_categories,
                    :retention_days, :is_child, :guardian_consent_ref,
                    :status, :granted_at, CAST(:metadata AS jsonb)
                )
            """),
            {
                "consent_id":           record.consent_id,
                "principal_id":         record.principal_id,
                "data_fiduciary_id":    record.data_fiduciary_id,
                "purpose_ids":          record.purpose_ids,
                "legal_basis":          record.legal_basis.value,
                "data_categories":      record.data_categories,
                "retention_days":       record.retention_days,
                "is_child":             record.is_child,
                "guardian_consent_ref": record.guardian_consent_ref,
                "status":               record.status.value,
                "granted_at":           record.granted_at,
                "metadata":             json.dumps(record.metadata),
            }
        )
        await self.session.commit()

    async def get_consent(
        self, consent_id: str, principal_id: str
    ) -> Optional[ConsentRecord]:
        result = await self.session.execute(
            text("""
                SELECT consent_id, principal_id, data_fiduciary_id,
                       purpose_ids, legal_basis, data_categories,
                       retention_days, is_child, guardian_consent_ref,
                       status, granted_at, withdrawn_at, metadata
                FROM consent_records
                WHERE consent_id = :cid AND principal_id = :pid
            """),
            {"cid": consent_id, "pid": principal_id}
        )
        row = result.fetchone()
        if not row:
            return None
        return self._row_to_record(row)

    async def withdraw_consent(
        self, consent_id: str, withdrawn_at: datetime, reason: Optional[str]
    ) -> None:
        await self.session.execute(
            text("""
                UPDATE consent_records
                SET status = 'withdrawn',
                    withdrawn_at = :withdrawn_at,
                    withdrawal_reason = :reason
                WHERE consent_id = :cid
            """),
            {"cid": consent_id, "withdrawn_at": withdrawn_at, "reason": reason}
        )
        await self.session.commit()

    async def check_active_consent(
        self, principal_id: str, fiduciary_id: str, purpose_id: str
    ) -> bool:
        result = await self.session.execute(
            text("""
                SELECT COUNT(*)
                FROM consent_records
                WHERE principal_id = :pid
                  AND data_fiduciary_id = :fid
                  AND status = 'active'
                  AND :purpose_id = ANY(purpose_ids)
            """),
            {"pid": principal_id, "fid": fiduciary_id, "purpose_id": purpose_id}
        )
        count = result.scalar()
        return (count or 0) > 0

    async def list_consents_for_principal(
        self, principal_id: str
    ) -> list[ConsentRecord]:
        result = await self.session.execute(
            text("""
                SELECT consent_id, principal_id, data_fiduciary_id,
                       purpose_ids, legal_basis, data_categories,
                       retention_days, is_child, guardian_consent_ref,
                       status, granted_at, withdrawn_at, metadata
                FROM consent_records
                WHERE principal_id = :pid
                ORDER BY granted_at DESC
                LIMIT 100
            """),
            {"pid": principal_id}
        )
        return [self._row_to_record(r) for r in result.fetchall()]

    async def get_fiduciary_stats(self, fiduciary_id: str) -> dict:
        result = await self.session.execute(
            text("""
                SELECT
                    status,
                    COUNT(*) as count,
                    COUNT(*) FILTER (WHERE is_child) as child_count
                FROM consent_records
                WHERE data_fiduciary_id = :fid
                GROUP BY status
            """),
            {"fid": fiduciary_id}
        )
        rows = result.fetchall()
        stats = {"fiduciary_id": fiduciary_id, "by_status": {}, "total": 0}
        for row in rows:
            stats["by_status"][row.status] = {
                "count": row.count,
                "child_count": row.child_count,
            }
            stats["total"] += row.count
        return stats

    @staticmethod
    def _row_to_record(row) -> ConsentRecord:
        return ConsentRecord(
            consent_id=str(row.consent_id),
            principal_id=row.principal_id,
            data_fiduciary_id=row.data_fiduciary_id,
            purpose_ids=list(row.purpose_ids),
            legal_basis=LegalBasis(row.legal_basis),
            data_categories=list(row.data_categories),
            retention_days=row.retention_days,
            is_child=row.is_child,
            guardian_consent_ref=row.guardian_consent_ref,
            status=ConsentStatus(row.status),
            granted_at=row.granted_at,
            withdrawn_at=row.withdrawn_at,
            metadata=dict(row.metadata) if row.metadata else {},
        )
