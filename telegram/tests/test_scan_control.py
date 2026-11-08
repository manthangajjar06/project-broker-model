import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import telegram.scan_control as scan_control


class ScanControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.lock = root / ".scan_lock.json"
        self.script = root / "crone-job" / "run_nifty100.py"
        self.worker = root / "telegram" / "scan_worker.py"
        self.logs = root / "telegram" / "logs"
        self.script.parent.mkdir(parents=True)
        self.worker.parent.mkdir(parents=True)
        self.script.write_text("# fake\n", encoding="utf-8")
        self.worker.write_text("# fake\n", encoding="utf-8")
        self.patches = [
            patch.object(scan_control, "PROJECT_ROOT", root),
            patch.object(scan_control, "LOCK_FILE", self.lock),
            patch.object(scan_control, "SCAN_SCRIPT", self.script),
            patch.object(scan_control, "SCAN_WORKER", self.worker),
            patch.object(scan_control, "LOG_DIRECTORY", self.logs),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.tmp.cleanup()

    def test_status_clears_stale_lock(self):
        self.lock.write_text(json.dumps({"pid": 999999, "started_at": "t"}), encoding="utf-8")
        with patch.object(scan_control, "_pid_is_running", return_value=False):
            status = scan_control.get_status()
        self.assertFalse(status.running)
        self.assertFalse(self.lock.exists())

    def test_try_start_scan_writes_lock(self):
        process = MagicMock()
        process.pid = 4242
        with patch.object(scan_control.subprocess, "Popen", return_value=process) as popen:
            with patch.object(scan_control.time, "sleep"):
                with patch.object(scan_control, "_pid_is_running", return_value=True):
                    result = scan_control.try_start_scan(trigger="telegram", limit=2)

        self.assertTrue(result.started)
        self.assertTrue(self.lock.exists())
        payload = json.loads(self.lock.read_text(encoding="utf-8"))
        self.assertEqual(payload["pid"], 4242)
        self.assertEqual(payload["limit"], 2)
        self.assertEqual(payload["trigger"], "telegram")
        command = popen.call_args.args[0]
        self.assertIn("--limit", command)
        self.assertIn("2", command)

    def test_busy_scan_is_rejected(self):
        with patch.object(
            scan_control,
            "get_status",
            return_value=scan_control.ScanStatus(running=True, pid=1, started_at="t", trigger="nightly"),
        ):
            result = scan_control.try_start_scan(trigger="telegram")
        self.assertFalse(result.started)
        self.assertIn("already running", result.message.lower())


if __name__ == "__main__":
    unittest.main()
