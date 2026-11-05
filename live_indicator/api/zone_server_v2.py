"""Corrected, independent demand-zone API. Run on port 8002."""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import detector
from candidate_adapter import candles_to_dataframe
from zone_store import save_scan
from zone_tracker_v2 import build_zone_records


class ZoneScanRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=64)
    candles: list[dict] = Field(min_length=3)
    datr: float | None = Field(default=None, gt=0)


app = FastAPI(title="Demand Zone Scanner v2", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["https://kite.zerodha.com"], allow_methods=["POST"], allow_headers=["Content-Type"])


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": "2", "rule_1": "leg_out_open"}


@app.post("/zones")
def zones(request: ZoneScanRequest) -> dict:
    try:
        dataframe = candles_to_dataframe(request.candles)
        records = build_zone_records(dataframe, detector.run_detection(dataframe), request.symbol, request.datr)
        save_scan(request.symbol, records)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"status": "ok", "symbol": request.symbol, "zones": records}
