from __future__ import annotations

from app.config import get_settings


cfg = get_settings()

BOT_NAME = "instagram_scraper_service"

SPIDER_MODULES = ["scraper.spiders"]
NEWSPIDER_MODULE = "scraper.spiders"

ROBOTSTXT_OBEY = False
COOKIES_ENABLED = False

CONCURRENT_REQUESTS = 2
DOWNLOAD_DELAY = (cfg.min_delay_seconds + cfg.max_delay_seconds) / 2
RANDOMIZE_DOWNLOAD_DELAY = True

RETRY_ENABLED = True
RETRY_TIMES = cfg.retries
RETRY_HTTP_CODES = [401, 402, 403, 408, 429, 500, 502, 503, 504]

DOWNLOAD_TIMEOUT = cfg.request_timeout_seconds

AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = cfg.min_delay_seconds
AUTOTHROTTLE_MAX_DELAY = cfg.max_delay_seconds * 2
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
AUTOTHROTTLE_DEBUG = False

DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

DOWNLOADER_MIDDLEWARES = {
    "scraper.middlewares.RandomUserAgentMiddleware": 400,
}

LOG_ENABLED = True
LOG_LEVEL = "INFO"
