"""Kafka event publisher for consent lifecycle events — lazy connection with retry."""

import asyncio
import json
from datetime import datetime

import structlog
from aiokafka import AIOKafkaProducer

from config import Settings
from models import ConsentRecord

log = structlog.get_logger()


class ConsentEventPublisher:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._producer: AIOKafkaProducer | None = None
        self._lock = asyncio.Lock()

    async def _get_producer(self) -> AIOKafkaProducer:
        """Lazy connect with retry — Kafka may not be ready at service startup."""
        if self._producer is not None:
            return self._producer

        async with self._lock:
            if self._producer is not None:
                return self._producer

            for attempt in range(1, 6):
                try:
                    producer = AIOKafkaProducer(
                        bootstrap_servers=self._settings.kafka_bootstrap,
                        value_serializer=lambda v: json.dumps(v, default=str).encode(),
                        request_timeout_ms=5000,
                    )
                    await producer.start()
                    self._producer = producer
                    log.info("kafka.producer.connected", attempt=attempt)
                    return self._producer
                except Exception as e:
                    log.warning("kafka.producer.retry", attempt=attempt, error=str(e))
                    if attempt < 5:
                        await asyncio.sleep(3 * attempt)

            log.error("kafka.producer.unavailable", msg="Proceeding without Kafka")
            return None

    async def start(self):
        """Called at startup — non-fatal if Kafka not ready yet."""
        try:
            await self._get_producer()
        except Exception as e:
            log.warning("kafka.startup.skipped", error=str(e))

    async def stop(self):
        if self._producer:
            await self._producer.stop()
            self._producer = None

    async def _publish(self, event_type: str, payload: dict):
        producer = await self._get_producer()
        if producer is None:
            log.warning("kafka.publish.skipped", event_type=event_type,
                        reason="Kafka not available")
            return

        envelope = {
            "event_type": event_type,
            "source": "consent-engine",
            "ts": datetime.utcnow().isoformat(),
            **payload,
        }
        try:
            await producer.send_and_wait(
                self._settings.kafka_consent_topic,
                value=envelope,
            )
            log.info("kafka.event.published", event_type=event_type)
        except Exception as e:
            log.error("kafka.publish.failed", event_type=event_type, error=str(e))
            self._producer = None  # Reset so next call retries

    async def publish_consent_granted(self, record: ConsentRecord):
        await self._publish("CONSENT_GRANTED", {
            "consent_id":        record.consent_id,
            "principal_id":      record.principal_id,
            "data_fiduciary_id": record.data_fiduciary_id,
            "purpose_ids":       record.purpose_ids,
            "legal_basis":       record.legal_basis,
            "data_categories":   record.data_categories,
            "is_child":          record.is_child,
        })

    async def publish_consent_withdrawn(
        self,
        consent_id: str,
        principal_id: str,
        withdrawn_at: datetime,
        reason: str | None,
    ):
        await self._publish("CONSENT_WITHDRAWN", {
            "consent_id":   consent_id,
            "principal_id": principal_id,
            "withdrawn_at": withdrawn_at.isoformat(),
            "reason":       reason,
        })
