"""HTTP boundary for the live indicator service."""

from contextlib import asynccontextmanager
from pathlib import Path

import lightgbm as lgb
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from candidate_adapter import build_candidate_rows
from feature_engineering import extract_features


MODEL_PATH = Path(__file__).resolve().parents[1] / "model" / "model.txt"


class PredictionRequest(BaseModel):
    candles: list[dict] = Field(min_length=3)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        app.state.model = lgb.Booster(model_file=str(MODEL_PATH))
        app.state.model_loaded = True
        app.state.model_error = None
    except Exception as error:
        app.state.model = None
        app.state.model_loaded = False
        app.state.model_error = str(error)
    yield


app = FastAPI(title="Live Indicator API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://kite.zerodha.com"],
    allow_methods=["POST"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok" if app.state.model_loaded else "degraded",
        "model_loaded": app.state.model_loaded,
        "model_error": app.state.model_error,
    }


@app.post("/predict")
def predict(request: PredictionRequest) -> dict:
    """Detect rule candidates and score them with the loaded LightGBM model."""
    if not app.state.model_loaded:
        raise HTTPException(status_code=503, detail="Prediction model is unavailable.")

    try:
        candidate_rows = build_candidate_rows(request.candles)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    if candidate_rows.empty:
        return {"status": "ok", "received_candles": len(request.candles), "signals": []}

    model_features = extract_features(candidate_rows)
    probabilities = app.state.model.predict(model_features)
    signals = []
    for (_, candidate), probability in zip(candidate_rows.iterrows(), probabilities):
        acceptance_confidence = float(probability) * 100
        rejection_confidence = 100 - acceptance_confidence
        prediction = "accepted" if acceptance_confidence >= 50 else "rejected"
        signals.append({
            "type": candidate["pattern_type"],
            "mode": candidate["leg_out_mode"],
            "time": candidate["end_timestamp"],
            "zone_high": float(candidate["zone_high"]),
            "zone_low": float(candidate["zone_low"]),
            "prediction": prediction,
            "acceptance_confidence_pct": round(acceptance_confidence, 2),
            "rejection_confidence_pct": round(rejection_confidence, 2),
        })

    return {
        "status": "ok",
        "received_candles": len(request.candles),
        "signals": signals,
    }
