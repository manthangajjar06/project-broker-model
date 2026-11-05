"""Small SQLite history store for the standalone zone scanner."""

import json
import sqlite3
from pathlib import Path


DEFAULT_DATABASE = Path(__file__).resolve().parents[1] / "zone_history.sqlite3"


def save_scan(symbol: str, zones: list[dict], database: Path = DEFAULT_DATABASE) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS zone_history (
                zone_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                status TEXT NOT NULL,
                formed_at TEXT NOT NULL,
                draw_until TEXT,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        for zone in zones:
            connection.execute("""
                INSERT INTO zone_history (zone_id, symbol, status, formed_at, draw_until, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(zone_id) DO UPDATE SET
                    status=excluded.status, draw_until=excluded.draw_until,
                    payload_json=excluded.payload_json, updated_at=CURRENT_TIMESTAMP
            """, (zone["zone_id"], symbol, zone["status"], zone["formed_at"], zone["draw_until"], json.dumps(zone)))
