"""
DPDP Compliance OS - Combined Service
All microservices mounted as sub-applications under one FastAPI app.
One Railway service, one URL, all endpoints available.

Endpoints:
  /                          → Root + service index
  /health                    → Combined health check
  /docs                      → This combined Swagger UI
  /role-classifier/...       → Role Classifier (Day 1)
  /sdf/...                   → SDF Determinator (Day 2)
  /dpia/...                  → DPIA Engine (Day 2)
  /bias/...                  → AI Bias Monitor (Day 2)
  /transfer/...              → Cross-Border PEP (Day 2)
  /score/...                 → Compliance Score (Day 6)
  /pbac/...                  → PBAC Engine (Day 7)
  /shadow-ai/...             → Shadow AI Discovery (Day 8)
  /rag/...                   → RAG Corpus Privacy (Day 8)
"""

import importlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ── Add all service directories to Python path ────────────────────────────
BASE = Path(__file__).parent
SERVICES = {
    "role_classifier":    BASE / "day1" / "role-classifier",
    "sdf_determinator":   BASE / "day2" / "sdf-determinator",
    "dpia_engine":        BASE / "day2" / "dpia-engine",
    "ai_bias_monitor":    BASE / "day2" / "ai-bias-monitor",
    "cross_border_pep":   BASE / "day2" / "cross-border-pep",
    "compliance_score":   BASE / "day6" / "compliance-score",
    "pbac_engine":        BASE / "day7" / "pbac-engine",
    "shadow_ai":          BASE / "day8" / "shadow-ai-discovery",
    "rag_privacy":        BASE / "day8" / "rag-corpus-privacy",
}

# Add each service dir to sys.path so their imports work
for name, path in SERVICES.items():
    if path.exists() and str(path) not in sys.path:
        sys.path.insert(0, str(path))

# ── Root app ──────────────────────────────────────────────────────────────
root = FastAPI(
    title="DPDP Compliance OS",
    description="""
## DPDP + AI Compliance Operating System

All services combined in one deployment.

| Service | Prefix | Day |
|---|---|---|
| Role Classifier | `/role-classifier` | 1 |
| SDF Determinator | `/sdf` | 2 |
| DPIA Engine | `/dpia` | 2 |
| AI Bias Monitor | `/bias` | 2 |
| Cross-Border PEP | `/transfer` | 2 |
| Compliance Score | `/score` | 6 |
| PBAC Engine | `/pbac` | 7 |
| Shadow AI Discovery | `/shadow-ai` | 8 |
| RAG Corpus Privacy | `/rag` | 8 |
""",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

root.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Health endpoint ────────────────────────────────────────────────────────
@root.get("/health", tags=["System"])
async def health():
    return {
        "status": "ok",
        "service": "dpdp-compliance-os",
        "ts": datetime.now(timezone.utc).isoformat(),
        "services_loaded": list(loaded.keys()),
        "services_failed": list(failed.keys()),
    }

@root.get("/", tags=["System"])
async def index():
    return {
        "name": "DPDP Compliance OS",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "services": {
            "role-classifier":  "/role-classifier/docs",
            "sdf-determinator": "/sdf/docs",
            "dpia-engine":      "/dpia/docs",
            "ai-bias-monitor":  "/bias/docs",
            "cross-border-pep": "/transfer/docs",
            "compliance-score": "/score/docs",
            "pbac-engine":      "/pbac/docs",
            "shadow-ai":        "/shadow-ai/docs",
            "rag-privacy":      "/rag/docs",
        }
    }

# ── Mount each service app ─────────────────────────────────────────────────
loaded = {}
failed = {}

MOUNTS = [
    ("role_classifier",  "/role-classifier", "role-classifier"),
    ("sdf_determinator", "/sdf",             "sdf-determinator"),
    ("dpia_engine",      "/dpia",            "dpia-engine"),
    ("ai_bias_monitor",  "/bias",            "ai-bias-monitor"),
    ("cross_border_pep", "/transfer",        "cross-border-pep"),
    ("compliance_score", "/score",           "compliance-score"),
    ("pbac_engine",      "/pbac",            "pbac-engine"),
    ("shadow_ai",        "/shadow-ai",       "shadow-ai-discovery"),
    ("rag_privacy",      "/rag",             "rag-corpus-privacy"),
]

for module_key, prefix, svc_name in MOUNTS:
    try:
        mod = importlib.import_module("main")
        # Each service has its own main.py - we need to reload after path change
        # Use importlib with the specific path
        import importlib.util
        svc_path = SERVICES[module_key] / "main.py"
        spec = importlib.util.spec_from_file_location(f"main_{module_key}", svc_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        svc_app = mod.app
        root.mount(prefix, svc_app, name=svc_name)
        loaded[svc_name] = prefix
        print(f"  Mounted: {svc_name} at {prefix}")
    except Exception as e:
        failed[svc_name] = str(e)
        print(f"  FAILED: {svc_name} - {e}")

print(f"\nDPDP Compliance OS ready: {len(loaded)} services mounted, {len(failed)} failed")
