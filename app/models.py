from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl


class InstagramProfile(BaseModel):
    username: str = Field(..., description="Instagram handle queried")
    full_name: Optional[str] = Field(None, description="Public full name if available")
    biography: Optional[str] = Field(None, description="Short biography text")
    followers: int = Field(..., description="Follower count reported by Instagram")
    profile_picture_url: Optional[HttpUrl] = Field(
        None,
        description="Direct URL to the user's high-resolution profile picture",
    )
    profile_image_path: Optional[str] = Field(
        None,
        description="Local filesystem path to the saved profile image (if downloaded)",
    )
    is_cached: bool = Field(
        default=False,
        description="True when the response was served from the local cache instead of a fresh scrape.",
    )
    scraped_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the data was scraped",
    )


class ScrapeResponse(BaseModel):
    data: InstagramProfile


class ScrapeErrorResponse(BaseModel):
    detail: str
