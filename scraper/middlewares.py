from __future__ import annotations

import random
from typing import Iterable

from scrapy.http import Request


USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.6312.86 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edg/123.0.2420.65 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_1_2) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.6312.122 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.128 Safari/537.36",
)


SEC_CH_UA_VALUES: tuple[str, ...] = (
    '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    '"Chromium";v="122", "Microsoft Edge";v="122", "Not=A?Brand";v="99"',
    '"Google Chrome";v="123", "Chromium";v="123", "Not.A/Brand";v="8"',
)

SEC_CH_UA_PLATFORM: tuple[str, ...] = (
    '"Windows"',
    '"macOS"',
    '"Linux"',
)


class RandomUserAgentMiddleware:
    """Rotate User-Agent strings and fingerprint-like headers per request."""

    def __init__(self, user_agents: Iterable[str]):
        self.user_agents = tuple(user_agents)

    @classmethod
    def from_crawler(cls, crawler):
        return cls(USER_AGENTS)

    def process_request(self, request: Request, spider) -> None:  # noqa: D401
        user_agent = random.choice(self.user_agents)
        request.headers["User-Agent"] = user_agent
        request.headers["Sec-CH-UA"] = random.choice(SEC_CH_UA_VALUES)
        request.headers["Sec-CH-UA-Platform"] = random.choice(SEC_CH_UA_PLATFORM)
        request.headers["Sec-CH-UA-Mobile"] = "?0"
        request.headers["Pragma"] = "no-cache"
        request.headers["Cache-Control"] = "no-cache"

        # Add small jitter per-request to avoid deterministic timing
        if "download_slot" not in request.meta:
            request.meta["download_slot"] = user_agent
        request.meta.setdefault("download_delay", random.uniform(2.0, 5.0))


__all__ = ["RandomUserAgentMiddleware"]
