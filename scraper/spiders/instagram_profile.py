from __future__ import annotations

import json
import random
import re
from html import unescape
from typing import Dict, Optional

import scrapy
from scrapy.http import Request, Response
from scrapy.spidermiddlewares.httperror import HttpError
from twisted.internet.error import DNSLookupError, TCPTimedOutError, TimeoutError
from twisted.python.failure import Failure

from app.config import get_settings


class InstagramProfileSpider(scrapy.Spider):
    name = "instagram_profile"
    allowed_domains = ["www.instagram.com", "instagram.com"]

    class ProfileNotFound(Exception):
        """Raised when a profile does not exist or is private."""

    class RateLimited(Exception):
        """Raised when Instagram returns HTTP 429."""

    class ProxyTimeout(Exception):
        """Raised when the request timed out (often proxy issues)."""

    def __init__(
        self,
        username: str,
        result_buffer: list[dict],
        proxy_url: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.username = username.strip().lstrip("@")
        self.result_buffer = result_buffer
        self.proxy_url = proxy_url
        cfg = get_settings()
        self.download_timeout = cfg.request_timeout_seconds
        self.cookies = cfg.instagram_cookies()
        self.app_id = cfg.instagram_app_id

    # ------------------------------------------------------------------ #
    # Entry points
    # ------------------------------------------------------------------ #
    def start_requests(self):
        meta = {
            "handle_httpstatus_list": [200, 302, 400, 403, 404, 429],
            "download_timeout": self.download_timeout,
        }
        if self.proxy_url:
            meta["proxy"] = self.proxy_url

        mobile_url = (
            f"https://i.instagram.com/api/v1/users/web_profile_info/"
            f"?username={self.username}"
        )
        yield Request(
            mobile_url,
            callback=self.parse_mobile_api,
            errback=self.errback,
            headers=self._build_mobile_api_headers(),
            meta=meta,
            dont_filter=True,
        )

    # ------------------------------------------------------------------ #
    # Parsers
    # ------------------------------------------------------------------ #
    def parse_mobile_api(self, response: Response, **kwargs):
        status = response.status
        if status == 404:
            raise self.ProfileNotFound(f"Instagram profile '{self.username}' not found.")

        if status == 429:
            raise self.RateLimited("Instagram responded with HTTP 429 Too Many Requests.")

        if status == 200 and response.text.strip():
            try:
                payload = response.json()
            except json.JSONDecodeError:
                payload = None

            user = (payload or {}).get("data", {}).get("user") if payload else None
            if user:
                result = self._build_result_from_user(user)
                self.result_buffer.append(result)
                return

        yield from self._schedule_web_api(response)

    def parse_api_v1(self, response: Response, **kwargs):
        status = response.status
        self.logger.info(
            "API v1 response status=%s length=%s for %s",
            status,
            len(response.text),
            self.username,
        )

        if status == 404:
            raise self.ProfileNotFound(f"Instagram profile '{self.username}' not found.")

        if status == 429:
            raise self.RateLimited("Instagram responded with HTTP 429 Too Many Requests.")

        if status == 200:
            try:
                payload = response.json()
            except json.JSONDecodeError:
                payload = None

            user = (payload or {}).get("data", {}).get("user") if payload else None
            if user:
                result = self._build_result_from_user(user)
                self.result_buffer.append(result)
                return

        # Fall back to legacy JSON endpoint if web profile API is unavailable
        yield from self._schedule_legacy_json(response)

    def parse_legacy_json(self, response: Response, **kwargs):
        status = response.status

        if status == 404:
            raise self.ProfileNotFound(f"Instagram profile '{self.username}' not found.")

        if status == 429:
            raise self.RateLimited("Instagram responded with HTTP 429 Too Many Requests.")

        if status >= 400 or not response.text.strip():
            yield from self._schedule_html_fallback(response)
            return

        try:
            payload = response.json()
        except json.JSONDecodeError:
            yield from self._schedule_html_fallback(response)
            return

        user = (
            payload.get("graphql", {}).get("user")
            or payload.get("data", {}).get("user")
            or payload.get("items", [{}])[0].get("user", {})
        )

        if not user:
            yield from self._schedule_html_fallback(response)
            return

        result = self._build_result_from_user(user)
        self.result_buffer.append(result)

    def parse_html(self, response: Response, **kwargs):
        status = response.status

        if status == 404:
            raise self.ProfileNotFound(f"Instagram profile '{self.username}' not found.")
        if status == 429:
            raise self.RateLimited("Instagram responded with HTTP 429 Too Many Requests.")

        parsed = self._extract_from_html(response.text)
        if not parsed:
            raise self.ProfileNotFound(
                f"Unable to extract data from Instagram profile '{self.username}'."
            )

        self.result_buffer.append(parsed)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _schedule_legacy_json(self, response: Response):
        meta = response.meta.copy()
        headers = self._build_headers(json_request=True)
        json_url = f"https://www.instagram.com/{self.username}/?__a=1&__d=dis"
        self.logger.info("Falling back to legacy JSON for %s", self.username)

        yield Request(
            json_url,
            callback=self.parse_legacy_json,
            errback=self.errback,
            headers=headers,
            cookies=self.cookies,
            meta=meta,
            dont_filter=True,
        )

    def _schedule_web_api(self, response: Response):
        meta = response.meta.copy()
        headers = self._build_api_headers()
        api_url = (
            f"https://www.instagram.com/api/v1/users/web_profile_info/"
            f"?username={self.username}"
        )
        self.logger.info("Falling back to web API for %s", self.username)

        yield Request(
            api_url,
            callback=self.parse_api_v1,
            errback=self.errback,
            headers=headers,
            cookies=self.cookies,
            meta=meta,
            dont_filter=True,
        )

    def _schedule_html_fallback(self, response: Response):
        meta = response.meta.copy()
        headers = self._build_headers(json_request=False)
        html_url = f"https://www.instagram.com/{self.username}/"
        self.logger.info("Falling back to HTML parsing for %s", self.username)

        yield Request(
            html_url,
            callback=self.parse_html,
            errback=self.errback,
            headers=headers,
            cookies=self.cookies,
            meta=meta,
            dont_filter=True,
        )

    def _build_headers(self, *, json_request: bool) -> Dict[str, str]:
        chrome_build = random.choice(
            (
                "124.0.6367.118",
                "123.0.6312.124",
                "122.0.6261.128",
            )
        )
        base_headers = {
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": f"https://www.instagram.com/{self.username}/",
            "DNT": "1",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Dest": "empty" if json_request else "document",
            "Sec-Fetch-Mode": "cors" if json_request else "navigate",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
        }

        if json_request:
            base_headers["Accept"] = "application/json, text/javascript, */*; q=0.01"
            base_headers["X-Requested-With"] = "XMLHttpRequest"
        else:
            base_headers["Accept"] = (
                "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
                "image/webp,*/*;q=0.8"
            )

        base_headers["X-IG-App-ID"] = self.app_id
        if self.cookies.get("csrftoken"):
            base_headers["X-CSRFToken"] = self.cookies["csrftoken"]

        return base_headers

    def _build_api_headers(self) -> Dict[str, str]:
        chrome_build = random.choice(
            (
                "124.0.6367.118",
                "123.0.6312.124",
                "122.0.6261.128",
            )
        )
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                f"(KHTML, like Gecko) Chrome/{chrome_build} Safari/537.36"
            ),
            "Accept": "application/json",
            "Referer": f"https://www.instagram.com/{self.username}/",
            "X-IG-App-ID": self.app_id,
            "DNT": "1",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
            "X-Requested-With": "XMLHttpRequest",
        }
        if self.cookies.get("csrftoken"):
            headers["X-CSRFToken"] = self.cookies["csrftoken"]
        return headers

    def _build_mobile_api_headers(self) -> Dict[str, str]:
        return {
            "User-Agent": (
                "Instagram 219.0.0.12.117 Android (26/8.0.0; 640dpi; 1440x2560; "
                "Google; Pixel 3 XL; Crosshatch; qcom; en_US; 123456789)"
            ),
            "Accept": "application/json",
            "Accept-Language": "en-US",
            "X-IG-App-ID": "567067343352427",
            "X-IG-Capabilities": "3brTvw==",
            "X-IG-Connection-Type": "WIFI",
            "X-IG-Connection-Speed": "0kbps",
            "X-IG-Bandwidth-Speed-KBPS": "0.000",
            "X-IG-Bandwidth-TotalBytes-B": "0",
            "X-IG-Bandwidth-TotalTime-MS": "0",
        }

    def _build_result_from_user(self, user_payload: dict) -> dict:
        followers = (
            user_payload.get("edge_followed_by", {}) or {}
        ).get("count")
        profile_pic = (
            user_payload.get("profile_pic_url_hd")
            or user_payload.get("profile_pic_url")
        )
        biography = user_payload.get("biography")

        return {
            "username": self.username,
            "full_name": user_payload.get("full_name"),
            "biography": biography if biography else None,
            "followers": int(followers or 0),
            "profile_picture_url": profile_pic,
        }

    def _extract_from_html(self, html: str) -> Optional[dict]:
        script_payload = self._extract_json_blob(html)
        if script_payload:
            user = (
                script_payload.get("entry_data", {})
                .get("ProfilePage", [{}])[0]
                .get("graphql", {})
                .get("user")
            )
            if user:
                return self._build_result_from_user(user)

        followers_match = re.search(
            r'"edge_followed_by"\s*:\s*\{"count"\s*:\s*(\d+)\}', html
        )
        pic_match = re.search(r'"profile_pic_url_hd"\s*:\s*"([^"]+)"', html)
        full_name_match = re.search(r'"full_name"\s*:\s*"([^"]*)"', html)
        bio_match = re.search(r'"biography"\s*:\s*"([^"]*)"', html)

        followers = int(followers_match.group(1)) if followers_match else 0
        profile_pic = None
        if pic_match:
            profile_pic = unescape(pic_match.group(1).encode("utf-8").decode("unicode_escape"))
            profile_pic = profile_pic.replace("\\u0026", "&")

        biography = None
        if bio_match:
            biography = unescape(bio_match.group(1).encode("utf-8").decode("unicode_escape"))

        if followers == 0 and not profile_pic:
            return None

        return {
            "username": self.username,
            "full_name": unescape(full_name_match.group(1)) if full_name_match else None,
            "biography": biography,
            "followers": followers,
            "profile_picture_url": profile_pic,
        }

    def _extract_json_blob(self, html: str) -> Optional[dict]:
        blob_match = re.search(
            r"window\.__additionalDataLoaded\('feed',(\{.*?\})\);", html, flags=re.DOTALL
        )
        if not blob_match:
            blob_match = re.search(
                r"window\._sharedData\s*=\s*(\{.*?\});", html, flags=re.DOTALL
            )

        if not blob_match:
            return None

        try:
            payload = json.loads(blob_match.group(1))
        except json.JSONDecodeError:
            return None
        return payload

    # ------------------------------------------------------------------ #
    # Error handling
    # ------------------------------------------------------------------ #
    def errback(self, failure: Failure):
        if failure.check(HttpError):
            response = failure.value.response
            status = response.status
            if status == 404:
                raise self.ProfileNotFound(f"Instagram profile '{self.username}' not found.")
            if status == 429:
                raise self.RateLimited("Instagram responded with HTTP 429 Too Many Requests.")

        if failure.check(TimeoutError, TCPTimedOutError, DNSLookupError):
            raise self.ProxyTimeout(f"Timeout while scraping '{self.username}'.") from failure.value

        raise failure.value
