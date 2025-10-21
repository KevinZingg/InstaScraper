from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv


logger = logging.getLogger(__name__)

load_dotenv()


def _split_csv(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass
class Settings:
    """Centralised configuration loaded from environment variables."""

    nord_username: Optional[str] = os.getenv("NORD_VPN_USERNAME")
    nord_password: Optional[str] = os.getenv("NORD_VPN_PASSWORD")
    socks5_host: Optional[str] = os.getenv("NORD_VPN_SOCKS5_HOST")
    socks5_port: Optional[int] = (
        int(os.getenv("NORD_VPN_SOCKS5_PORT", "1080"))
        if os.getenv("NORD_VPN_SOCKS5_PORT")
        else None
    )
    nord_api_token: Optional[str] = os.getenv("NORD_API_TOKEN")
    nord_proxy_pool: List[str] = field(
        default_factory=lambda: _split_csv(os.getenv("NORD_PROXY_POOL"))
    )

    instagram_sessionid: Optional[str] = os.getenv("INSTAGRAM_SESSIONID")
    instagram_csrftoken: Optional[str] = os.getenv("INSTAGRAM_CSRFTOKEN")
    instagram_app_id: str = os.getenv("INSTAGRAM_APP_ID", "936619743392459")
    instagram_username: Optional[str] = os.getenv("INSTAGRAM_USERNAME")
    instagram_password: Optional[str] = os.getenv("INSTAGRAM_PASSWORD")
    instagram_cookie_file: str = os.getenv("INSTAGRAM_COOKIE_FILE", "/data/instagram_cookies.json")

    # Scraping behaviour tuning knobs
    min_delay_seconds: float = float(os.getenv("SCRAPER_MIN_DELAY_SECONDS", "2.5"))
    max_delay_seconds: float = float(os.getenv("SCRAPER_MAX_DELAY_SECONDS", "6.5"))
    request_timeout_seconds: int = int(os.getenv("SCRAPER_TIMEOUT_SECONDS", "20"))
    retries: int = int(os.getenv("SCRAPER_RETRIES", "3"))
    proxy_retry_limit: int = int(os.getenv("PROXY_RETRY_LIMIT", "5"))
    proxy_backoff_seconds: float = float(os.getenv("PROXY_BACKOFF_SECONDS", "2.0"))

    api_auth_header: str = os.getenv("API_AUTH_HEADER", "X-API-Key")
    api_auth_key: Optional[str] = os.getenv("API_AUTH_KEY")

    # Persistence configuration
    database_path: str = os.getenv("DATABASE_PATH", "/data/scrapes.db")
    images_dir: str = os.getenv("IMAGES_DIR", "/data/images")

    def socks5_url(self, host: Optional[str] = None) -> Optional[str]:
        """Helper to construct the SOCKS5 proxy URL."""
        host = host or self.socks5_host
        if not (host and self.socks5_port and self.nord_username and self.nord_password):
            return None
        return f"socks5://{self.nord_username}:{self.nord_password}@{host}:{self.socks5_port}"

    def instagram_cookies(self) -> dict[str, str]:
        cookies: dict[str, str] = {}
        cookie_path = Path(self.instagram_cookie_file)
        if cookie_path.exists():
            try:
                data = json.loads(cookie_path.read_text())
                for key in ("sessionid", "csrftoken", "ds_user_id"):
                    value = data.get(key)
                    if value:
                        cookies[key] = value
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to read Instagram cookie file %s: %s", cookie_path, exc)

        if self.instagram_sessionid:
            cookies["sessionid"] = self.instagram_sessionid
        if self.instagram_csrftoken:
            cookies["csrftoken"] = self.instagram_csrftoken
        if cookies:
            cookies.setdefault("ig_nrcb", "1")
        return cookies


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton accessor so we only parse env vars once."""
    return Settings()
