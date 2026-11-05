"""Production replacement for the unified scanner. Run on port 8003."""

from contextlib import asynccontextmanager
from pathlib import Path
import inspect
import logging

import lightgbm as lgb
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from scan_support_fixed import InputError, build_zones, candidate_rows, detect_once, drop_forming_candle, prepare_dataframe, score_rows, WARMUP_BARS
from zone_store import save_scan

LOG = logging.getLogger(__name__)
MODEL_PATH = Path(__file__).resolve().parents[1] / "model" / "model.txt"

class ScanRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=64)
    candles: list[dict] = Field(min_length=3, max_length=20_000)

@asynccontextmanager
async def lifespan(app: FastAPI):
    try: app.state.model, app.state.model_error = lgb.Booster(model_file=str(MODEL_PATH)), None
    except Exception as error: app.state.model, app.state.model_error = None, str(error)
    yield

app = FastAPI(title="Unified Kite Demand Scanner", version="1.0.0", lifespan=lifespan)
cors = {"allow_origins": ["https://kite.zerodha.com"], "allow_methods": ["GET", "POST"], "allow_headers": ["Content-Type"]}
if "allow_private_network" in inspect.signature(CORSMiddleware.__init__).parameters: cors["allow_private_network"] = True
app.add_middleware(CORSMiddleware, **cors)

@app.get("/health")
def health() -> dict: return {"status": "ok" if app.state.model is not None else "degraded", "model_error": app.state.model_error}

@app.post("/scan")
def scan(request: ScanRequest) -> dict:
    try:
        dataframe, dropped = prepare_dataframe(request.candles)
        dataframe = drop_forming_candle(dataframe)
        if len(dataframe) < 3: return {"status": "ok", "zones": [], "meta": {"dropped_bars": dropped, "forming_bar_removed": True}}
        candidates = [c for c in detect_once(dataframe) if c["start_index"] >= WARMUP_BARS]
        zones = build_zones(dataframe, candidates, request.symbol)
    except InputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    try:
        scores = score_rows(candidate_rows(dataframe, candidates), app.state.model)
        for zone, score in zip(zones, scores): zone["ml"] = score
        ml_error = None
    except Exception as error:
        LOG.exception("Model scoring failed")
        for zone in zones: zone["ml"] = None
        ml_error = f"{type(error).__name__}: {error}"
    try: save_scan(request.symbol, zones)
    except Exception: LOG.exception("Zone history save failed")
    return {"status": "ok", "symbol": request.symbol, "zones": zones,
            "meta": {"dropped_bars": dropped, "warmup_bars": WARMUP_BARS, "last_closed_at": dataframe["timestamp"].iloc[-1].tz_localize("Asia/Kolkata").isoformat(), "ml_error": ml_error}}
