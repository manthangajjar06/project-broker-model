"""The history loader does not request candles until the enctoken is accepted."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from urllib.parse import parse_qs, urlparse  # noqa: E402

from history import (  # noqa: E402
    Minute,
    TokenRejected,
    build_candles,
    confirm_enctoken,
    decode_kite_body,
    drop_partial,
    load_minutes,
    normalize_token,
)


IST = ZoneInfo("Asia/Kolkata")


def bar(stamp, open_, high, low, close, volume):
    return [stamp, open_, high, low, close, volume, 0]


def test_web_page_is_not_shown_as_the_error():
    body = decode_kite_body("<!doctype html><html>cloudflare</html>")
    assert body["message"] == "Kite returned a web page instead of data."
    assert "<" not in body["message"]


def test_normalize_token_adds_prefix():
    assert normalize_token("abc") == "enctoken abc"
    assert normalize_token("enctoken abc") == "enctoken abc"
    assert normalize_token('"abc+def/=="') == "enctoken abc+def/=="
    assert normalize_token("  ") == ""


def test_missing_token_is_rejected_before_any_request():
    calls = []

    def get(url, authorization):
        calls.append(url)
        return 200, {"status": "success", "data": {"user_id": "IMN390"}}

    try:
        confirm_enctoken("", get)
    except TokenRejected:
        pass
    else:
        raise AssertionError("an empty token should be rejected")
    assert calls == []


def test_rejected_token_does_not_open_history():
    calls = []

    def get(url, authorization):
        calls.append(url)
        return 403, {"status": "error", "message": "Invalid session"}

    try:
        confirm_enctoken("enctoken expired", get)
    except TokenRejected as error:
        assert "Invalid session" in str(error)
    else:
        raise AssertionError("a rejected token should stop the run")
    assert "/historical/1270529/minute" in calls[0]
    assert "/user/profile" not in calls[0]


def test_walk_stops_at_the_gap_and_keeps_the_real_start():
    pages = {
        ("2015-05-14", "2015-07-11"): [bar("2015-05-14T09:15:00+0530", 288.64, 289.05, 286.64, 286.86, 1000)],
        ("2015-03-16", "2015-05-13"): [bar("2015-02-02T09:15:00+0530", 326, 327, 320, 321, 500)],
    }

    def get(url, authorization):
        query = parse_qs(urlparse(url).query)
        candles = pages.get((query["from"][0], query["to"][0]), [])
        return 200, {"status": "success", "data": {"candles": candles}}

    logs = []
    store = load_minutes(get, "enctoken ok", "1270529", "IMN390", "2015-07-11", sleep=lambda _seconds: None, log=logs.append)
    assert "2015-02-02" not in store
    assert "2015-05-14" in store
    assert store["2015-05-14"][0].open == 288.64
    assert any("gap before" in line for line in logs)


def test_normal_day_uses_the_chart_grid_and_muhurat_uses_its_own_open():
    normal = []
    for offset in range(180):
        minute = 9 * 60 + 15 + offset
        stamp = f"2015-05-14T{minute // 60:02d}:{minute % 60:02d}:00+0530"
        if minute == 11 * 60 + 15:
            normal.append(Minute(stamp, minute, 285, 286, 283, 284, 50))
        elif offset == 0:
            normal.append(Minute(stamp, minute, 288.64, 289.05, 286.64, 286.86, 100))
        else:
            normal.append(Minute(stamp, minute, 280, 281, 279, 280, 10))
    muhurat = [Minute("2018-11-07T17:30:00+0530", 17 * 60 + 30, 356.2, 357, 354.6, 355.9, 200)]
    candles, odd = build_candles({"2015-05-14": normal, "2018-11-07": muhurat})
    labels = [(candle.date, candle.time, candle.open) for candle in candles]
    assert ("2015-05-14", "09:15:00", 288.64) in labels
    assert ("2015-05-14", "11:15:00", 285) in labels
    assert ("2018-11-07", "17:30:00", 356.2) in labels
    assert any(day["date"] == "2018-11-07" and day["special"] for day in odd)


def test_today_unfinished_candle_is_dropped():
    candles, _odd = build_candles({
        "2026-11-13": [Minute("2026-11-13T09:15:00+0530", 9 * 60 + 15, 1576, 1586, 1572, 1580, 100)],
        "2026-11-12": [Minute("2026-11-12T09:15:00+0530", 9 * 60 + 15, 1500, 1510, 1490, 1505, 100)],
    })
    kept = drop_partial(candles, "2026-11-13", 10 * 60 + 58)
    assert [candle.date for candle in kept] == ["2026-11-12"]
    assert datetime(2026, 11, 13, 10, 58, tzinfo=IST).hour == 10
