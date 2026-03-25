"""
Vendor Risk Assessor - third-party processor risk
DPDP + AI Compliance OS
"""
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Vendor Risk Assessor", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "vendor-risk-assessor",
        "ts": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/")
async def root():
    return {
        "service": "vendor-risk-assessor",
        "docs": "/docs",
        "health": "/health",
    }
