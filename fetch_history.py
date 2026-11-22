"""Start the Nifty 100 history load from the project folder."""

import runpy
import sys
from pathlib import Path

folder = Path(__file__).resolve().parent / "RL" / "nifty100"
sys.path.insert(0, str(folder))
runpy.run_path(str(folder / "fetch_history.py"), run_name="__main__")
