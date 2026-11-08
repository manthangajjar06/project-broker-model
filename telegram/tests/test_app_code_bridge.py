import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import telegram.app_code_bridge as bridge


class AppCodeBridgeTests(unittest.TestCase):
    def test_publish_and_consume_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".pending_app_code"
            with patch.object(bridge, "PENDING_APP_CODE_FILE", path):
                bridge.publish_app_code("12-34-56")
                self.assertEqual(bridge.consume_app_code(), "123456")
                self.assertIsNone(bridge.consume_app_code())


if __name__ == "__main__":
    unittest.main()
