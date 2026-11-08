"""Semi-automatic Kite login for the scanner's Brave session.

* User IDs are remembered in ``~/.kite_zone_scanner/accounts.json`` (no secrets).
* Passwords live ONLY in the operating system's credential vault via
  ``keyring`` (Windows Credential Manager on Windows) - never in the project
  folder, never in plain text.
* The one-time "app code" (TOTP) is never stored: it is typed in the terminal
  each time because it changes every 30 seconds.
* Saved accounts are tried in order, one attempt each (so a wrong password is
  never hammered repeatedly); the next saved account is used if one is rejected.
"""

from __future__ import annotations

import asyncio
import getpass
import json
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

LOG = logging.getLogger("kite_login")

SERVICE_NAME = "kite-zone-scanner"
ACCOUNTS_FILE = Path.home() / ".kite_zone_scanner" / "accounts.json"
LOGIN_URL = "https://kite.zerodha.com/"
DASHBOARD_URL = "https://kite.zerodha.com/dashboard"

# Kite's login form.  If Zerodha changes its page, these are the only lines to edit.
USER_ID_FIELD = "input#userid"
PASSWORD_FIELD = "input#password"
SUBMIT_BUTTON = "button[type='submit']"
CHANGE_USER_LINK = "text=Change user"
TOTP_FIELD = "input[type='number'], input[label*='TOTP' i], input[maxlength='6']"
ERROR_TEXT = ".error, .su-message, [class*='error' i], [role='alert']"

MAX_TOTP_TRIES = 3


class LoginError(RuntimeError):
    """Raised when Kite cannot be logged in."""


# --------------------------------------------------------------------------
# Credential storage
# --------------------------------------------------------------------------
def _keyring() -> Any:
    try:
        import keyring
    except ImportError as error:
        raise LoginError("The 'keyring' package is missing. Run: python -m pip install keyring") from error
    return keyring


def list_accounts() -> list[str]:
    if not ACCOUNTS_FILE.is_file():
        return []
    try:
        return list(json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8")).get("user_ids", []))
    except (OSError, ValueError):
        return []


def _save_ids(user_ids: list[str]) -> None:
    ACCOUNTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACCOUNTS_FILE.write_text(json.dumps({"user_ids": user_ids}, indent=2), encoding="utf-8")


def add_account(user_id: str, password: str) -> None:
    """Save (or update) an account. A new ID goes to the end of the retry order."""

    user_id = user_id.strip().upper()
    if not user_id or not password:
        raise ValueError("User ID and password must both be non-empty.")
    _keyring().set_password(SERVICE_NAME, user_id, password)
    ids = list_accounts()
    if user_id not in ids:
        ids.append(user_id)
        _save_ids(ids)


def remove_account(user_id: str) -> bool:
    user_id = user_id.strip().upper()
    ids = list_accounts()
    if user_id not in ids:
        return False
    try:
        _keyring().delete_password(SERVICE_NAME, user_id)
    except Exception:  # already gone from the vault
        pass
    _save_ids([i for i in ids if i != user_id])
    return True


def get_password(user_id: str) -> str | None:
    return _keyring().get_password(SERVICE_NAME, user_id)


def prompt_and_save_account() -> str | None:
    """Ask in the terminal for a User ID and password (password is hidden)."""

    user_id = input("Kite User ID (blank to cancel): ").strip().upper()
    if not user_id:
        return None
    password = getpass.getpass("Kite password (hidden while typing): ")
    add_account(user_id, password)
    print(f"Saved {user_id} to the system credential vault.")
    return user_id


# --------------------------------------------------------------------------
# Browser steps
# --------------------------------------------------------------------------
async def _visible(page: Any, selector: str) -> bool:
    try:
        return await page.locator(selector).first.is_visible()
    except Exception:
        return False


async def is_logged_in(page: Any, timeout_seconds: int = 12) -> bool:
    """True when /dashboard stays open; False when Kite shows a login form."""

    await page.goto(DASHBOARD_URL, wait_until="domcontentloaded", timeout=45_000)
    for _ in range(timeout_seconds * 2):
        if await _visible(page, PASSWORD_FIELD):
            return False
        if "/dashboard" in page.url and not await _visible(page, USER_ID_FIELD):
            return True
        await page.wait_for_timeout(500)
    return False


async def select_user(page: Any, user_id: str) -> None:
    """Make the login form target ``user_id``.

    Kite has two layouts: a full form (User ID box + password) and, for a
    browser that has logged in before, a "remembered user" view that shows the
    ID as text with only a password box (the User ID input is hidden).
    """

    if await _visible(page, USER_ID_FIELD):
        await page.fill(USER_ID_FIELD, user_id)
        return

    shown = (await page.inner_text("body")).upper()
    if user_id.upper() in shown:
        LOG.info("Kite already shows %s - entering the password only.", user_id)
        return

    LOG.info("Kite remembers a different user - switching to %s.", user_id)
    await page.click(CHANGE_USER_LINK, timeout=10_000)
    await page.wait_for_selector(USER_ID_FIELD, state="visible", timeout=10_000)
    await page.fill(USER_ID_FIELD, user_id)


async def attempt_login(page: Any, user_id: str, password: str) -> str:
    """Submit one ID/password. Returns 'totp', 'ok', 'bad_credentials' or 'unknown'."""

    await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45_000)
    await page.wait_for_selector(PASSWORD_FIELD, state="visible", timeout=20_000)
    await select_user(page, user_id)
    await page.fill(PASSWORD_FIELD, password)
    await page.click(SUBMIT_BUTTON)

    for _ in range(40):  # up to 20 seconds
        await page.wait_for_timeout(500)
        if "/dashboard" in page.url:
            return "ok"
        if not await _visible(page, PASSWORD_FIELD) and await _visible(page, TOTP_FIELD):
            return "totp"
        if await _visible(page, ERROR_TEXT):
            return "bad_credentials"
    return "unknown"


async def _submit_totp(page: Any, field: Any) -> None:
    """Kite normally submits by itself at 6 digits; only nudge it if it did not.

    Every nudge is best-effort: once Kite accepts the code the page leaves the
    app-code step, so the button / box disappear and must not cause an error.
    """

    for _ in range(6):  # give Kite's own auto-submit ~3 seconds
        if "/dashboard" in page.url:
            return
        await page.wait_for_timeout(500)
    for nudge in (lambda: page.click(SUBMIT_BUTTON, timeout=2_000), lambda: field.press("Enter", timeout=2_000)):
        if "/dashboard" in page.url:
            return
        try:
            await nudge()
        except Exception:
            pass


async def submit_totp_code(page: Any, code: str) -> bool:
    """Type one app code into Kite and wait briefly for the dashboard.

    Returns True when the browser reaches ``/dashboard``. Returns False when
    Kite stays on the app-code step (usually because the digits expired).
    """

    cleaned = code.strip()
    if not cleaned:
        return False

    field = page.locator(TOTP_FIELD).first
    try:
        await field.fill("", timeout=5_000)
        await field.fill(cleaned, timeout=5_000)
    except Exception:
        if "/dashboard" in page.url:  # already through
            return True
        raise

    await _submit_totp(page, field)
    for _ in range(30):  # up to 15 seconds
        if "/dashboard" in page.url:
            return True
        await page.wait_for_timeout(500)
    return False


async def enter_totp(page: Any, user_id: str) -> bool:
    """Ask for the app code in the terminal and submit it. Up to 3 tries."""

    for attempt in range(1, MAX_TOTP_TRIES + 1):
        code = await asyncio.to_thread(
            input,
            f"[{user_id}] Enter the 6-digit app code (try {attempt}/{MAX_TOTP_TRIES}): ",
        )
        if await submit_totp_code(page, code):
            return True
        LOG.warning("App code was not accepted (it expires every 30 seconds).")
    return False


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
async def try_accounts(
    page: Any,
    user_ids: list[str],
    *,
    fetch_password: Callable[[str], str | None] = get_password,
    login: Callable[[Any, str, str], Awaitable[str]] = attempt_login,
    totp: Callable[[Any, str], Awaitable[bool]] = enter_totp,
) -> str | None:
    """Try each saved account once, in order. Return the User ID that logged in."""

    for user_id in user_ids:
        password = fetch_password(user_id)
        if not password:
            LOG.warning("%s has no saved password - skipping.", user_id)
            continue
        LOG.info("Trying saved account %s ...", user_id)
        outcome = await login(page, user_id, password)
        if outcome == "ok":
            return user_id
        if outcome == "totp":
            if await totp(page, user_id):
                return user_id
            LOG.warning("%s: app code failed; moving to the next saved account.", user_id)
        else:
            LOG.warning("%s: Kite rejected the login (%s); moving to the next saved account.", user_id, outcome)
    return None


async def ensure_logged_in(
    context: Any,
    *,
    totp: Callable[[Any, str], Awaitable[bool]] = enter_totp,
) -> str:
    """Make sure the browser is logged in to Kite; log in with saved accounts if not.

    ``totp`` defaults to the terminal prompt. The cron job can pass a Telegram
    based collector instead without changing the login page automation.
    """

    page = await context.new_page()
    try:
        if await is_logged_in(page):
            LOG.info("Kite is already logged in - no credentials needed.")
            return "already-logged-in"

        if not list_accounts():
            print("No saved Kite accounts yet. Add one now (stored in the system credential vault).")
            if await asyncio.to_thread(prompt_and_save_account) is None:
                raise LoginError("No Kite account available to log in with.")

        while True:
            winner = await try_accounts(page, list_accounts(), totp=totp)
            if winner:
                LOG.info("Logged in to Kite as %s.", winner)
                return winner
            print("None of the saved accounts could log in.")
            if await asyncio.to_thread(prompt_and_save_account) is None:
                raise LoginError("Could not log in to Kite with any saved account.")
    finally:
        # Closing the only open tab makes Brave quit, which kills the CDP port.
        # Keep the last page open so the browser survives for the scan phase.
        if len(page.context.pages) > 1:
            await page.close()