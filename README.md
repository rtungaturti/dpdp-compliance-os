# DPDP + AI Compliance Operating System

Production-ready implementation of the DPDP Act compliance platform across 8 build phases, with 63 containerised services.

---

## Architecture Improvements over SRS

| Gap in SRS | Fix Applied |
|---|---|
| No API gateway/ingress | **Traefik v3** — single entry point with routing, metrics, and label-based config |
| ZooKeeper for Kafka (deprecated) | **KRaft mode** — broker + controller in one process, no ZooKeeper |
| pgvector needed Day 8 only | **Enabled from Day 1** (`pgvector/pgvector:pg15` image) |
| No health checks | **`condition: service_healthy`** on all `depends_on` — prevents cascade failures |
| No incremental rollout | **Docker Compose profiles** — `--profile infra`, `--profile day1`, etc. |
| No distributed tracing | **OpenTelemetry Collector + Jaeger** from Day 1 — 54 services need tracing |

---

## Quick Start

```bash
# 1. Copy and configure environment
make env

# 2. Start infrastructure
make infra

# 3. Start Day 1 services
make day1

# 4. Smoke test
make test-consent
make test-classify
```

### Service URLs (Day 1)

| Service | URL |
|---|---|
| Consent Engine API | http://localhost:8003/docs |
| Role Classifier API | http://localhost:8001/docs |
| Lifecycle Mapper API | http://localhost:8002/docs |
| Rights Portal API | http://localhost:8004/docs |
| Traefik Dashboard | http://localhost:8080 |
| Jaeger Tracing UI | http://localhost:16686 |
| MinIO Console | http://localhost:9001 |
| Neo4j Browser | http://localhost:7474 |

---

## Directory Structure

```
dpdp-compliance-os/
├── Makefile
├── Dockerfile.base              # Shared base image
├── requirements.base.txt        # Shared Python dependencies
├── docker-compose.day1.yml      # Day 1 full stack
├── .env.example
├── infra/
│   ├── init-db/
│   │   └── 01_init.sql          # Postgres schema + pgvector
│   └── otel/
│       └── otel-config.yaml     # OpenTelemetry Collector config
└── services/
    └── day1/
        ├── consent-engine/      # DPDP §6-13 consent lifecycle
        │   ├── main.py
        │   ├── models.py
        │   ├── config.py
        │   ├── events.py
        │   └── Dockerfile
        ├── role-classifier/     # DPDP §2 SDF determination
        │   └── main.py
        ├── lifecycle-mapper/    # Data × AI lifecycle graph
        ├── rights-portal/       # Rights request intake
        ├── breach-simulator/    # Harm assessment + notification
        └── evidence-generator/  # Audit-ready evidence binders
```

---

## Day-by-Day Build Plan

| Day | Focus | Services | Status |
|---|---|---|---|
| **Day 1** | DPDP OS Foundation | 6 services + 9 infra | 🚀 Scaffolded |
| **Day 2** | Enforcement, SDF, DPIA, AI Governance | 6 services | 📋 Planned |
| **Day 3** | Consent & Preference Management | 5 services | 📋 Planned |
| **Day 4** | Rights Workflows + HITL | 6 services | 📋 Planned |
| **Day 5** | Breach Engineering + Lineage | 7 services | 📋 Planned |
| **Day 6** | Penalty & Compliance Score | 6 services | 📋 Planned |
| **Day 7** | Advanced Governance, PBAC | 6 services | 📋 Planned |
| **Day 8** | Integration + Elite AI Extensions | 8 services | 📋 Planned |

---

## Key DPDP Compliance References

- **§6** — Consent: Free, specific, informed, unconditional → `consent-engine`
- **§7** — Deemed consent (legitimate interest) → `role-classifier` + `deemed-use-analyzer`
- **§9** — Children's data: guardian consent required → `consent-engine` guard
- **§10** — Significant Data Fiduciary obligations → `role-classifier` SDF detection
- **§11** — Rights requests: 30-day SLA → `rights-portal` + `sla-tracker`
- **§13** — Withdrawal must be as easy as granting → `consent-engine` + `withdrawal-propagator`
"# dpdp-compliance-os" 
