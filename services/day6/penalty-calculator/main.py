"""
Penalty Calculator - DPDP S33 exposure modeling
DPDP + AI Compliance OS
"""
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Penalty Calculator", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "penalty-calculator",
        "ts": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/")
async def root():
    return {
        "service": "penalty-calculator",
        "docs": "/docs",
        "health": "/health",
    }
