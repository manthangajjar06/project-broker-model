"""Child process entry: open a log file, then run the NIFTY 100 scanner.

``scan_control`` starts this script detached so Task Scheduler / the Telegram
bot can exit (or keep listening) while the scan continues with its own log.
"""

from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCAN_SCRIPT = PROJECT_ROOT / "crone-job" / "run_nifty100.py"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-file", required=True, help="Append stdout/stderr here")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    log_path = Path(args.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    log_handle = log_path.open("a", encoding="utf-8")
    sys.stdout = log_handle
    sys.stderr = log_handle

    if not SCAN_SCRIPT.is_file():
        print(f"Scan script not found: {SCAN_SCRIPT}", flush=True)
        return 1

    # Build argv the way run_nifty100.main() expects when executed as a script.
    sys.argv = [str(SCAN_SCRIPT)]
    if args.limit is not None:
        sys.argv.extend(["--limit", str(args.limit)])

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    job_directory = str(SCAN_SCRIPT.parent)
    if job_directory not in sys.path:
        sys.path.insert(0, job_directory)

    try:
        runpy.run_path(str(SCAN_SCRIPT), run_name="__main__")
    except SystemExit as exit_info:
        code = exit_info.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        return 1
    except Exception:
        import traceback

        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
