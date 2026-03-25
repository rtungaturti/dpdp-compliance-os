"""
Evidence Generator - audit-ready evidence binder
DPDP + AI Compliance OS
"""
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Evidence Generator", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "evidence-generator",
        "ts": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/")
async def root():
    return {
        "service": "evidence-generator",
        "docs": "/docs",
        "health": "/health",
    }
