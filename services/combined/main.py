"""
DPDP Compliance OS - Combined App
All services in one process. 3 containers: app + postgres + redis.
Swagger: /docs
"""

import importlib.util
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Resolve base path - works both locally and in Docker (/app/combined/main.py)
THIS_FILE = Path(__file__).resolve()
BASE = THIS_FILE.parent.parent  # /app/services or E:\COS\services

print(f"Combined app starting. BASE={BASE}")
print(f"Contents of BASE: {list(p.name for p in BASE.iterdir() if p.is_dir())}")

MOUNTS = [
    ("role_classifier",  "day1/role-classifier",    "/role-classifier"),
    ("consent_engine",   "day1/consent-engine",      "/consent"),
    ("sdf_determinator", "day2/sdf-determinator",    "/sdf"),
    ("dpia_engine",      "day2/dpia-engine",          "/dpia"),
    ("ai_bias_monitor",  "day2/ai-bias-monitor",      "/bias"),
    ("cross_border_pep", "day2/cross-border-pep",     "/transfer"),
    ("compliance_score", "day6/compliance-score",     "/score"),
    ("pbac_engine",      "day7/pbac-engine",           "/pbac"),
    ("shadow_ai",        "day8/shadow-ai-discovery",  "/shadow-ai"),
    ("rag_privacy",      "day8/rag-corpus-privacy",   "/rag"),
]

root = FastAPI(
    title="DPDP Compliance OS",
    description="""
**DPDP + AI Compliance Operating System** — All services combined.

| Prefix | Service | Day |
|--------|---------|-----|
| `/role-classifier` | Role Classifier | 1 |
| `/consent` | Consent Engine | 1 |
| `/sdf` | SDF Determinator | 2 |
| `/dpia` | DPIA Engine | 2 |
| `/bias` | AI Bias Monitor | 2 |
| `/transfer` | Cross-Border PEP | 2 |
| `/score` | Compliance Score | 6 |
| `/pbac` | PBAC Engine | 7 |
| `/shadow-ai` | Shadow AI Discovery | 8 |
| `/rag` | RAG Corpus Privacy | 8 |
""",
    version="1.0.0",
)

root.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

loaded = {}
failed = {}


def load_service(key, rel_path, prefix):
    svc_dir = BASE / rel_path
    main_file = svc_dir / "main.py"

    if not main_file.exists():
        raise FileNotFoundError(f"Not found: {main_file}")

    # Add service dir to sys.path so local imports (models, config, db) work
    svc_str = str(svc_dir)
    if svc_str not in sys.path:
        sys.path.insert(0, svc_str)

    # Load module with unique name to avoid conflicts
    spec = importlib.util.spec_from_file_location(f"svc_{key}", str(main_file))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"svc_{key}"] = mod  # Register to avoid re-import issues
    spec.loader.exec_module(mod)

    root.mount(prefix, mod.app, name=key)
    loaded[key] = prefix
    print(f"  OK  {rel_path} -> {prefix}")


@root.get("/health", tags=["System"])
async def health():
    return {
        "status": "ok",
        "service": "dpdp-compliance-os",
        "ts": datetime.now(timezone.utc).isoformat(),
        "loaded": len(loaded),
        "failed": len(failed),
        "services": {
            **{k: {"status": "ok",     "prefix": v} for k, v in loaded.items()},
            **{k: {"status": "failed", "error":  v} for k, v in failed.items()},
        }
    }


@root.get("/", tags=["System"])
async def index():
    return {
        "name":    "DPDP Compliance OS",
        "version": "1.0.0",
        "docs":    "/docs",
        "health":  "/health",
        "loaded":  len(loaded),
        "failed":  len(failed),
        "endpoints": {k: f"{v}/docs" for k, v in loaded.items()},
    }


# Load all services at startup
print("\nLoading services...")
for key, rel_path, prefix in MOUNTS:
    try:
        load_service(key, rel_path, prefix)
    except Exception as e:
        err = str(e)
        tb = traceback.format_exc()
        failed[key] = err
        print(f"  FAIL {rel_path}: {err}")
        print(f"       {tb.splitlines()[-2] if len(tb.splitlines())>2 else tb}")

print(f"\nReady: {len(loaded)} loaded, {len(failed)} failed\n")
