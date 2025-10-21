from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Dict, Optional

import requests
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from app.config import get_settings


logger = logging.getLogger(__name__)
COOKIE_KEYS = {"sessionid", "csrftoken", "ds_user_id"}
COOKIE_VALIDATION_HANDLE = "instagram"


def _cookie_file_path() -> Path:
    settings = get_settings()
    return Path(settings.instagram_cookie_file)


def load_persisted_cookies() -> Dict[str, str]:
    path = _cookie_file_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        logger.warning("Corrupted Instagram cookie file at %s. Ignoring.", path)
        return {}
    return {k: v for k, v in data.items() if k in COOKIE_KEYS and v}


def save_cookies(cookies: Dict[str, str]) -> None:
    path = _cookie_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {key: value for key, value in cookies.items() if key in COOKIE_KEYS}
    path.write_text(json.dumps(payload))
    logger.info("Persisted Instagram session cookies to %s", path)


def _validate_cookies(cookies: Dict[str, str]) -> bool:
    if not cookies.get("sessionid"):
        return False
    headers = {
        "User-Agent": (
            "Instagram 219.0.0.12.117 Android (26/8.0.0; 640dpi; 1440x2560; "
            "Google; Pixel 3 XL; Crosshatch; qcom; en_US; 123456789)"
        ),
        "Accept": "application/json",
        "X-IG-App-ID": "567067343352427",
        "Accept-Language": "en-US",
        "X-IG-Capabilities": "3brTvw==",
        "X-IG-Connection-Type": "WIFI",
    }
    try:
        resp = requests.get(
            f"https://i.instagram.com/api/v1/users/web_profile_info/?username={COOKIE_VALIDATION_HANDLE}",
            headers=headers,
            cookies=cookies,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return bool(data.get("data", {}).get("user"))
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to validate Instagram cookies: %s", exc)
        return False


def _login_and_get_cookies(username: str, password: str) -> Optional[Dict[str, str]]:
    logger.info("Attempting headless Instagram login for %s", username)
    start = time.time()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context()
            page = context.new_page()
            page.goto("https://www.instagram.com/accounts/login/", wait_until="networkidle")
            page.fill('input[name="username"]', username)
            page.fill('input[name="password"]', password)
            page.click('button[type="submit"]')
            try:
                page.wait_for_url("https://www.instagram.com/", wait_until="networkidle", timeout=30000)
            except PlaywrightTimeoutError:
                logger.error("Instagram login did not redirect to the home feed. Check credentials or challenges.")
                return None

            cookies = context.cookies()
            cookie_map = {cookie["name"]: cookie["value"] for cookie in cookies if cookie.get("name") in COOKIE_KEYS}
            if not cookie_map.get("sessionid"):
                logger.error("Instagram login succeeded but no sessionid cookie was found.")
                return None
            logger.info("Headless Instagram login completed in %.2fs", time.time() - start)
            return cookie_map
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error while logging into Instagram: %s", exc)
        return None


def ensure_instagram_session(force_refresh: bool = False) -> Dict[str, str]:
    """Ensure we have a valid Instagram session. Returns active cookies."""
    settings = get_settings()
    cookies = load_persisted_cookies()
    env_cookies = settings.instagram_cookies()
    cookies.update(env_cookies)

    if not force_refresh and cookies and _validate_cookies(cookies):
        return cookies

    if not (settings.instagram_username and settings.instagram_password):
        logger.info("Instagram credentials not provided; continuing without authenticated session.")
        return cookies

    fresh_cookies = _login_and_get_cookies(settings.instagram_username, settings.instagram_password)
    if not fresh_cookies:
        logger.warning("Unable to obtain Instagram session cookies automatically.")
        return cookies

    save_cookies(fresh_cookies)
    cookies.update(fresh_cookies)
    return cookies
