"""One sidecar API for ML confidence signals and corrected demand zones.

Run: python -m uvicorn unified_server:app --port 8003
"""

from contextlib import asynccontextmanager
from pathlib import Path

import lightgbm as lgb
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import detector
from candidate_adapter import build_candidate_rows, candles_to_dataframe
from feature_engineering import extract_features
from zone_store import save_scan
from zone_tracker_v2 import build_zone_records


MODEL_PATH = Path(__file__).resolve().parents[1] / "model" / "model.txt"


class ScanRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=64)
    candles: list[dict] = Field(min_length=3)
    datr: float | None = Field(default=None, gt=0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        app.state.model = lgb.Booster(model_file=str(MODEL_PATH))
        app.state.model_error = None
    except Exception as error:
        app.state.model = None
        app.state.model_error = str(error)
    yield


app = FastAPI(title="Unified Kite Demand Scanner", version="0.3.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["https://kite.zerodha.com"], allow_methods=["POST"], allow_headers=["Content-Type"])


@app.get("/health")
def health() -> dict:
    return {"status": "ok" if app.state.model is not None else "degraded", "model_error": app.state.model_error}


@app.post("/scan")
def scan(request: ScanRequest) -> dict:
    try:
        dataframe = candles_to_dataframe(request.candles)
        candidates = detector.run_detection(dataframe)
        zones = build_zone_records(dataframe, candidates, request.symbol, request.datr)
        save_scan(request.symbol, zones)
        rows = build_candidate_rows(request.candles)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    signals = []
    if not rows.empty and app.state.model is not None:
        for (_, row), probability in zip(rows.iterrows(), app.state.model.predict(extract_features(rows))):
            accepted_pct = float(probability) * 100
            accepted = accepted_pct >= 50
            signals.append({
                "type": row["pattern_type"], "time": row["end_timestamp"],
                "zone_high": float(row["zone_high"]), "zone_low": float(row["zone_low"]),
                "prediction": "accepted" if accepted else "rejected",
                "acceptance_confidence_pct": round(accepted_pct, 2),
                "rejection_confidence_pct": round(100 - accepted_pct, 2),
            })
    return {"status": "ok", "symbol": request.symbol, "signals": signals, "zones": zones}
