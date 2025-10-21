from __future__ import annotations

import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

from app.config import get_settings
from app.models import InstagramProfile


logger = logging.getLogger(__name__)
_settings = get_settings()
_db_lock = threading.Lock()
_db_path = Path(_settings.database_path)
_images_dir = Path(_settings.images_dir)


def init_storage() -> None:
    """Ensure directories exist and the SQLite schema is created."""
    _images_dir.mkdir(parents=True, exist_ok=True)
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    with _get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS profile_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                full_name TEXT,
                biography TEXT,
                followers INTEGER NOT NULL,
                profile_picture_url TEXT,
                profile_image_path TEXT,
                scraped_at TEXT NOT NULL,
                is_cached INTEGER DEFAULT 0
            )
            """
        )
        conn.commit()


@contextmanager
def _get_connection():
    with _db_lock:
        conn = sqlite3.connect(_db_path, check_same_thread=False)
        try:
            yield conn
        finally:
            conn.close()


def persist_profile(profile: InstagramProfile) -> InstagramProfile:
    """
    Save scrape metadata to SQLite and download the profile image locally.

    Returns a new ``InstagramProfile`` instance with the ``profile_image_path``
    field populated if the download succeeds.
    """

    local_image_path = None
    image_source_url = str(profile.profile_picture_url) if profile.profile_picture_url else None
    if image_source_url:
        local_image_path, image_source_url = _download_image(
            profile.username,
            image_source_url,
            profile.scraped_at,
        )

    update_payload = {
        "profile_image_path": local_image_path,
        "is_cached": False,
    }
    if image_source_url and not profile.profile_picture_url:
        update_payload["profile_picture_url"] = image_source_url

    serialised_profile = profile.model_copy(update=update_payload)

    picture_url_str = (
        str(serialised_profile.profile_picture_url)
        if serialised_profile.profile_picture_url
        else None
    )

    with _get_connection() as conn:
        conn.execute(
            """
            INSERT INTO profile_snapshots (
                username,
                full_name,
                biography,
                followers,
                profile_picture_url,
                profile_image_path,
                scraped_at,
                is_cached
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                serialised_profile.username,
                serialised_profile.full_name,
                serialised_profile.biography,
                serialised_profile.followers,
                picture_url_str,
                serialised_profile.profile_image_path,
                serialised_profile.scraped_at.isoformat(),
                int(serialised_profile.is_cached),
            ),
        )
        conn.commit()

    return serialised_profile


def _download_image(username: str, url: str, scraped_at: datetime) -> tuple[Optional[str], Optional[str]]:
    """
    Fetch and persist the profile image; returns the relative path if successful.

    Instagram serves profile images with signed URLs that include query parameters;
    we normalise the filename to ``<username>_<timestamp>.jpg`` but respect any
    extension hints in the URL when available.
    """
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix or ".jpg"
    timestamp = scraped_at.strftime("%Y%m%d%H%M%S")
    filename = f"{username}_{timestamp}{suffix}"
    destination = _images_dir / filename

    if destination.exists():
        return str(destination)

    def fetch_image(target_url: str) -> Optional[bytes]:
        try:
            response = requests.get(target_url, timeout=30)
            response.raise_for_status()
            return response.content
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to download profile image for %s from %s: %s",
                username,
                target_url,
                exc,
            )
            return None

    content = fetch_image(url)

    if content is None and "unavatar.io" not in url:
        fallback_url = f"https://unavatar.io/instagram/{username}"
        content = fetch_image(fallback_url)
        if content is not None:
            url = fallback_url

    if content is None:
        fallback_url = f"https://api.dicebear.com/7.x/initials/png?seed={username}"
        content = fetch_image(fallback_url)
        if content is not None:
            url = fallback_url

    if content is None:
        return None, None

    try:
        destination.write_bytes(content)
        return str(destination), url
    except OSError as exc:
        logger.error("Unable to persist profile image for %s: %s", username, exc)
        return None, None


def get_latest_profile(username: str) -> Optional[InstagramProfile]:
    """Load the most recent cached profile snapshot for ``username`` if available."""

    with _get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT username, full_name, biography, followers, profile_picture_url,
                   profile_image_path, scraped_at, is_cached
            FROM profile_snapshots
            WHERE username = ?
            ORDER BY datetime(scraped_at) DESC
            LIMIT 1
            """,
            (username,),
        )
        row = cursor.fetchone()

    if not row:
        return None

    scraped_at = datetime.fromisoformat(row[6])
    return InstagramProfile(
        username=row[0],
        full_name=row[1],
        biography=row[2],
        followers=row[3],
        profile_picture_url=row[4],
        profile_image_path=row[5],
        scraped_at=scraped_at,
        is_cached=bool(row[7]),
    )
