from __future__ import annotations

import logging
import random
import threading
import time
from collections import deque
from typing import Deque, Optional

import requests

from app.config import get_settings


logger = logging.getLogger(__name__)


class ProxyManager:
    """Manage a rotating pool of NordVPN SOCKS5 endpoints with basic cooldowns."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._lock = threading.Lock()
        initial_pool = self.settings.nord_proxy_pool or []
        self._pool: Deque[str] = deque(initial_pool)
        self._bad_hosts: dict[str, float] = {}
        if not self._pool:
            self._refresh_pool()

    def _refresh_pool(self) -> None:
        """Fetch a fresh recommendation list from the NordVPN public API."""
        try:
            response = requests.get(
                "https://api.nordvpn.com/v1/servers/recommendations",
                params={"filters[supported_protocols][0]": "socks", "limit": 25},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            hosts = [item["hostname"] for item in data if "hostname" in item]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Unable to refresh NordVPN SOCKS pool: %s", exc)
            hosts = []

        random.shuffle(hosts)
        if hosts:
            logger.info("Loaded %s SOCKS5 hosts from NordVPN API", len(hosts))
            self._pool.extend(hosts)

    def get_next_host(self) -> Optional[str]:
        """Return the next viable SOCKS5 host or ``None`` if exhausted."""
        with self._lock:
            now = time.time()
            attempts = 0
            max_attempts = len(self._pool) or 0

            while self._pool and attempts <= max_attempts:
                host = self._pool[0]
                self._pool.rotate(-1)
                attempts += 1
                available_at = self._bad_hosts.get(host)
                if available_at and available_at > now:
                    continue
                return host

            if not self._pool:
                self._refresh_pool()
            if not self._pool:
                return None

            host = self._pool[0]
            self._pool.rotate(-1)
            return host

    def mark_bad(self, host: str, cooldown_seconds: float = 300.0) -> None:
        with self._lock:
            self._bad_hosts[host] = time.time() + cooldown_seconds
            logger.info("Marking SOCKS5 host %s as bad for %.0f seconds", host, cooldown_seconds)


_PROXY_MANAGER: Optional[ProxyManager] = None


def get_proxy_manager() -> ProxyManager:
    global _PROXY_MANAGER
    if _PROXY_MANAGER is None:
        _PROXY_MANAGER = ProxyManager()
    return _PROXY_MANAGER
