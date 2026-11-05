import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kite_login


class FakeKeyring:
    def __init__(self):
        self.vault = {}

    def set_password(self, service, user, password):
        self.vault[(service, user)] = password

    def get_password(self, service, user):
        return self.vault.get((service, user))

    def delete_password(self, service, user):
        del self.vault[(service, user)]


class CredentialStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [
            patch.object(kite_login, "ACCOUNTS_FILE", Path(self.tmp.name) / "accounts.json"),
            patch.object(kite_login, "_keyring", return_value=FakeKeyring()),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_password_goes_to_vault_not_to_the_ids_file(self):
        kite_login.add_account("ab1234", "s3cret!")
        self.assertEqual(kite_login.list_accounts(), ["AB1234"])
        self.assertEqual(kite_login.get_password("AB1234"), "s3cret!")
        self.assertNotIn("s3cret!", kite_login.ACCOUNTS_FILE.read_text())

    def test_order_is_kept_and_removal_works(self):
        kite_login.add_account("AAA111", "a")
        kite_login.add_account("BBB222", "b")
        kite_login.add_account("AAA111", "a2")  # update, not duplicate
        self.assertEqual(kite_login.list_accounts(), ["AAA111", "BBB222"])
        self.assertTrue(kite_login.remove_account("AAA111"))
        self.assertEqual(kite_login.list_accounts(), ["BBB222"])
        self.assertFalse(kite_login.remove_account("NOPE"))


class RetryTests(unittest.TestCase):
    def run_flow(self, outcomes, totp_ok=True):
        tried = []

        async def login(page, user, password):
            tried.append((user, password))
            return outcomes[user]

        async def totp(page, user):
            return totp_ok

        passwords = {"A": "pa", "B": "pb", "C": None}
        winner = asyncio.run(kite_login.try_accounts(
            object(), ["A", "B", "C"], fetch_password=passwords.get, login=login, totp=totp))
        return winner, tried

    def test_falls_through_to_next_account_after_rejection(self):
        winner, tried = self.run_flow({"A": "bad_credentials", "B": "totp"})
        self.assertEqual(winner, "B")
        self.assertEqual(tried, [("A", "pa"), ("B", "pb")])  # one attempt each

    def test_account_without_saved_password_is_skipped(self):
        winner, tried = self.run_flow({"A": "unknown", "B": "bad_credentials"})
        self.assertIsNone(winner)
        self.assertEqual([u for u, _ in tried], ["A", "B"])

    def test_failed_app_code_moves_on(self):
        winner, _ = self.run_flow({"A": "totp", "B": "totp"}, totp_ok=False)
        self.assertIsNone(winner)


class FakePage:
    """Minimal stand-in for a Playwright page showing Kite's login form."""

    def __init__(self, userid_visible, body_text):
        self.userid_visible = userid_visible
        self.body_text = body_text
        self.filled = {}
        self.clicked = []

    def locator(self, selector):
        page = self

        class First:
            async def is_visible(inner):
                return page.userid_visible if selector == kite_login.USER_ID_FIELD else False

        class Loc:
            first = First()

        return Loc()

    async def inner_text(self, selector):
        return self.body_text

    async def fill(self, selector, value):
        if selector == kite_login.USER_ID_FIELD and not self.userid_visible:
            raise AssertionError("tried to fill a hidden User ID box")
        self.filled[selector] = value

    async def click(self, selector, timeout=None):
        self.clicked.append(selector)
        if selector == kite_login.CHANGE_USER_LINK:
            self.userid_visible = True

    async def wait_for_selector(self, selector, state=None, timeout=None):
        return None


class SelectUserTests(unittest.TestCase):
    def test_full_form_fills_user_id(self):
        page = FakePage(True, "Login")
        asyncio.run(kite_login.select_user(page, "IMN390"))
        self.assertEqual(page.filled[kite_login.USER_ID_FIELD], "IMN390")

    def test_remembered_same_user_skips_user_id(self):
        page = FakePage(False, "IMN390\nChange user\nPassword")
        asyncio.run(kite_login.select_user(page, "imn390"))
        self.assertEqual(page.filled, {})
        self.assertEqual(page.clicked, [])

    def test_remembered_other_user_clicks_change_user(self):
        page = FakePage(False, "ABC123\nChange user\nPassword")
        asyncio.run(kite_login.select_user(page, "IMN390"))
        self.assertEqual(page.clicked, [kite_login.CHANGE_USER_LINK])
        self.assertEqual(page.filled[kite_login.USER_ID_FIELD], "IMN390")


class TotpPage:
    """Kite auto-submits the code: the page jumps to /dashboard and the box vanishes."""

    def __init__(self, auto_submit=True):
        self.url = "https://kite.zerodha.com/"
        self.auto_submit = auto_submit
        self.clicks = 0
        outer = self

        class Field:
            async def fill(inner, value, timeout=None):
                if value and outer.auto_submit:
                    outer.url = "https://kite.zerodha.com/dashboard"

            async def press(inner, key, timeout=None):
                raise TimeoutError("element is gone")

        class Loc:
            first = Field()

        self._loc = Loc()

    def locator(self, selector):
        return self._loc

    async def click(self, selector, timeout=None):
        self.clicks += 1
        raise TimeoutError("button is gone")

    async def wait_for_timeout(self, ms):
        return None


class EnterTotpTests(unittest.TestCase):
    def test_auto_submitted_code_succeeds_without_touching_vanished_elements(self):
        page = TotpPage(auto_submit=True)
        with patch("builtins.input", return_value="018659"):
            self.assertTrue(asyncio.run(kite_login.enter_totp(page, "IMN390")))
        self.assertEqual(page.clicks, 0)

    def test_rejected_code_returns_false_after_three_tries_without_crashing(self):
        page = TotpPage(auto_submit=False)
        with patch("builtins.input", return_value="000000"):
            self.assertFalse(asyncio.run(kite_login.enter_totp(page, "IMN390")))


if __name__ == "__main__":
    unittest.main()