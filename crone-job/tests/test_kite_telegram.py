import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import kite_telegram


class FakeTotpPage:
    def __init__(self, accept_codes):
        self.url = "https://kite.zerodha.com/"
        self.accept_codes = set(accept_codes)
        self.submitted = []
        outer = self

        class Field:
            async def fill(inner, value, timeout=None):
                if value:
                    outer.submitted.append(value)
                    if value in outer.accept_codes:
                        outer.url = "https://kite.zerodha.com/dashboard"

            async def press(inner, key, timeout=None):
                return None

        class Loc:
            first = Field()

        self._loc = Loc()

    def locator(self, selector):
        return self._loc

    async def click(self, selector, timeout=None):
        return None

    async def wait_for_timeout(self, ms):
        return None


class EnterTotpViaTelegramTests(unittest.TestCase):
    def test_accepts_first_valid_code(self):
        page = FakeTotpPage(accept_codes={"123456"})
        with (
            patch.object(kite_telegram.notify, "notify_app_code_needed") as needed,
            patch.object(kite_telegram.notify, "notify_app_code_received") as received,
            patch.object(kite_telegram.notify, "notify_app_code_accepted") as accepted,
            patch.object(kite_telegram, "wait_for_app_code", return_value="123456"),
        ):
            ok = asyncio.run(kite_telegram.enter_totp_via_telegram(page, "AB1234"))

        self.assertTrue(ok)
        self.assertEqual(page.submitted, ["123456"])
        needed.assert_called_once()
        received.assert_called_once()
        accepted.assert_called_once_with("AB1234")

    def test_retries_after_rejected_code_then_succeeds(self):
        page = FakeTotpPage(accept_codes={"999999"})
        codes = iter(["000000", "999999"])
        with (
            patch.object(kite_telegram.notify, "notify_app_code_needed"),
            patch.object(kite_telegram.notify, "notify_app_code_received"),
            patch.object(kite_telegram.notify, "notify_app_code_accepted"),
            patch.object(kite_telegram.notify, "notify_app_code_rejected") as rejected,
            patch.object(kite_telegram, "wait_for_app_code", side_effect=lambda **kwargs: next(codes)),
        ):
            ok = asyncio.run(kite_telegram.enter_totp_via_telegram(page, "AB1234"))

        self.assertTrue(ok)
        self.assertEqual(page.submitted, ["000000", "999999"])
        rejected.assert_called_once()

    def test_timeouts_exhaust_attempts(self):
        page = FakeTotpPage(accept_codes=set())
        with (
            patch.object(kite_telegram.notify, "notify_app_code_needed"),
            patch.object(kite_telegram.notify, "notify_app_code_timeout") as timed_out,
            patch.object(kite_telegram, "wait_for_app_code", return_value=None),
        ):
            ok = asyncio.run(kite_telegram.enter_totp_via_telegram(page, "AB1234"))

        self.assertFalse(ok)
        self.assertEqual(timed_out.call_count, 3)


if __name__ == "__main__":
    unittest.main()
