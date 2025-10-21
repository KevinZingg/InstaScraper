from __future__ import annotations

import logging
import socket
import asyncio
from typing import List, Optional
from urllib.parse import urlparse


def _proxy_reachable(proxy_url: str) -> bool:
    """Quick TCP connectivity check for a SOCKS5 proxy before using it."""
    parsed = urlparse(proxy_url)
    host = parsed.hostname
    port = parsed.port or 1080
    if not host:
        return False

    try:
        with socket.create_connection((host, port), timeout=5):
            return True
    except OSError as exc:
        logger.warning("SOCKS5 proxy %s unreachable: %s", proxy_url, exc)
        return False

import crochet
from scrapy.crawler import CrawlerRunner
from scrapy.settings import Settings as ScrapySettings

from app.config import get_settings
from app.models import InstagramProfile
from app.proxy_manager import get_proxy_manager
from scraper import settings as project_settings
from scraper.spiders.instagram_profile import InstagramProfileSpider


logger = logging.getLogger(__name__)


# Ensure the Twisted reactor is running in the background
crochet.setup()


_SCRAPY_RUNNER: Optional[CrawlerRunner] = None


class ProfileNotFoundError(Exception):
    """Raised when Instagram responds with a 404 or profile data is missing."""


class RateLimitError(Exception):
    """Raised when Instagram responds with a rate limiting status."""


class ScraperRuntimeError(Exception):
    """Raised for unexpected failures during scraping."""


def _get_runner() -> CrawlerRunner:
    global _SCRAPY_RUNNER
    if _SCRAPY_RUNNER is None:
        settings = ScrapySettings()
        settings.setmodule(project_settings)
        _SCRAPY_RUNNER = CrawlerRunner(settings)
    return _SCRAPY_RUNNER


@crochet.wait_for(timeout=None)
def _run_spider(username: str, result_buffer: List[dict], proxy_url: Optional[str]) -> None:
    runner = _get_runner()
    return runner.crawl(
        InstagramProfileSpider,
        username=username,
        result_buffer=result_buffer,
        proxy_url=proxy_url,
    )


async def scrape_instagram_profile(username: str) -> InstagramProfile:
    """
    Scrape public Instagram data for ``username`` and return a structured payload.

    Raises:
        ProfileNotFoundError: if the profile does not exist or is private.
        RateLimitError: if Instagram signals rate limiting (HTTP 429).
        ScraperRuntimeError: for any other scraping failures.
    """

    settings = get_settings()
    proxy_manager = get_proxy_manager()
    result_buffer: List[dict] = []
    failure_reasons: List[str] = []

    async def run_with_proxy(proxy_url: Optional[str]) -> None:
        await asyncio.to_thread(
            _run_spider,
            username=username,
            result_buffer=result_buffer,
            proxy_url=proxy_url,
        )

    # Try rotating through SOCKS5 proxies first
    proxy_attempts = 0
    while proxy_attempts < settings.proxy_retry_limit:
        host = proxy_manager.get_next_host()
        if not host:
            break
        proxy_attempts += 1
        proxy_url = settings.socks5_url(host)
        if not proxy_url:
            break

        if not _proxy_reachable(proxy_url):
            proxy_manager.mark_bad(host, cooldown_seconds=600)
            continue

        try:
            await run_with_proxy(proxy_url)
            logger.info("Scraped %s via proxy %s", username, host)
            break
        except InstagramProfileSpider.ProxyTimeout as exc:
            logger.warning("Proxy timeout for %s via %s: %s", username, host, exc)
            proxy_manager.mark_bad(host, cooldown_seconds=600)
            failure_reasons.append(f"Proxy timeout via {host}")
            await asyncio.sleep(settings.proxy_backoff_seconds)
            continue
        except InstagramProfileSpider.RateLimited as exc:
            proxy_manager.mark_bad(host, cooldown_seconds=600)
            logger.warning("Rate limited for %s via %s: %s", username, host, exc)
            raise RateLimitError(str(exc)) from exc
        except InstagramProfileSpider.ProfileNotFound as exc:
            raise ProfileNotFoundError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            proxy_manager.mark_bad(host, cooldown_seconds=600)
            logger.warning("Proxy %s failed for %s: %s", host, username, exc)
            failure_reasons.append(f"Proxy {host} unexpected error: {exc}")
            await asyncio.sleep(settings.proxy_backoff_seconds)
            continue

    if not result_buffer:
        # Fall back to direct connection
        try:
            await run_with_proxy(None)
        except InstagramProfileSpider.ProfileNotFound as exc:
            raise ProfileNotFoundError(str(exc)) from exc
        except InstagramProfileSpider.RateLimited as exc:
            raise RateLimitError(str(exc)) from exc
        except InstagramProfileSpider.ProxyTimeout as exc:
            failure_reasons.append("Direct connection timeout")
            raise ScraperRuntimeError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected scraping failure for %s", username)
            failure_reasons.append(f"Direct connection error: {exc}")
            raise ProfileNotFoundError(
                f"Instagram profile '{username}' is unavailable or private. {exc}"
            ) from exc

    if not result_buffer:
        logger.warning("Scrape completed with empty buffer for %s", username)
        detail = ", ".join(failure_reasons) if failure_reasons else "No data returned"
        raise ProfileNotFoundError(
            f"Instagram profile '{username}' is unavailable or private. {detail}"
        )

    return InstagramProfile(**result_buffer[0])
