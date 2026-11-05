import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_nifty100


class BraveStartupTests(unittest.TestCase):
    def test_does_not_launch_when_cdp_is_already_ready(self):
        with (
            patch.object(run_nifty100, "_cdp_is_ready", return_value=True),
            patch.object(run_nifty100.subprocess, "Popen") as popen,
        ):
            run_nifty100.ensure_brave_running(run_nifty100.DEFAULT_CDP_URL)
        popen.assert_not_called()

    def test_launches_brave_and_waits_for_cdp(self):
        process = Mock()
        process.poll.return_value = None
        executable = Mock()
        executable.is_file.return_value = True
        with (
            patch.object(run_nifty100, "_cdp_is_ready", side_effect=[False, False, True]),
            patch.object(run_nifty100.subprocess, "Popen", return_value=process) as popen,
            patch.object(run_nifty100.time, "sleep"),
        ):
            run_nifty100.ensure_brave_running(
                run_nifty100.DEFAULT_CDP_URL,
                brave_executable=executable,
                profile_directory=Path(r"C:\brave-debug-profile"),
            )
        command = popen.call_args.args[0]
        self.assertEqual(command[1], "--remote-debugging-port=9222")
        self.assertEqual(command[2], r"--user-data-dir=C:\brave-debug-profile")

    def test_does_not_launch_brave_for_unreachable_remote_cdp(self):
        with (
            patch.object(run_nifty100, "_cdp_is_ready", return_value=False),
            patch.object(run_nifty100.subprocess, "Popen") as popen,
        ):
            with self.assertRaisesRegex(RuntimeError, "remote debugging endpoint"):
                run_nifty100.ensure_brave_running("http://broker-host.example:9222")
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
