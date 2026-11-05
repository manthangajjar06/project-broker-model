"""Start the fixed unified local Live Indicator API."""

import sys
from pathlib import Path

import uvicorn


API_DIR = Path(__file__).resolve().parent / "api"
sys.path.insert(0, str(API_DIR))

from unified_server_fixed import app  # noqa: E402


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8003)
