from __future__ import annotations

import asyncio
import logging

from fastapi import Depends, FastAPI, HTTPException, Path, Request
from fastapi.responses import JSONResponse

from app.auth import ensure_instagram_session
from app.config import get_settings
from app.models import InstagramProfile, ScrapeErrorResponse, ScrapeResponse
from app.persistence import get_latest_profile, init_storage, persist_profile
from app.scraper_service import (
    ProfileNotFoundError,
    RateLimitError,
    ScraperRuntimeError,
    scrape_instagram_profile,
)


logger = logging.getLogger(__name__)

# Built for kevinzingg.ch
app = FastAPI(
    title="Instagram Scraper Service",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    description=(
        "Scrape Instagram profile metadata (follower count and profile picture) "
        "with proxy rotation and basic evasion strategies."
    ),
)


@app.on_event("startup")
async def startup_event() -> None:
    init_storage()
    await asyncio.to_thread(ensure_instagram_session)


async def require_api_key(request: Request) -> None:
    settings = get_settings()
    expected = settings.api_auth_key
    if not expected:
        return

    header_name = settings.api_auth_header or "X-API-Key"
    provided = request.headers.get(header_name.lower()) or request.headers.get(header_name)
    if provided != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


@app.get("/health", response_model=dict[str, str])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get(
    "/instagram/{username}",
    response_model=ScrapeResponse,
    responses={
        404: {"model": ScrapeErrorResponse},
        429: {"model": ScrapeErrorResponse},
        500: {"model": ScrapeErrorResponse},
    },
)
async def get_instagram_profile(
    username: str = Path(..., min_length=1, description="Instagram username to scrape"),
    _: None = Depends(require_api_key),
) -> ScrapeResponse:
    handle = username.strip().lstrip("@")
    if not handle:
        raise HTTPException(status_code=400, detail="Username must not be empty.")

    try:
        profile: InstagramProfile = await scrape_instagram_profile(handle)
        profile = await asyncio.to_thread(persist_profile, profile)
    except ProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ScraperRuntimeError as exc:
        logger.warning("Scraping error for %s: %s", handle, exc)
        cached = await asyncio.to_thread(get_latest_profile, handle)
        if cached:
            cached = cached.model_copy(update={"is_cached": True})
            return ScrapeResponse(data=cached)
        logger.exception("No cached data available for %s", handle)
        raise HTTPException(status_code=500, detail="Failed to scrape user data.") from exc

    return ScrapeResponse(data=profile)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):  # noqa: ANN001
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content=ScrapeErrorResponse(detail="Internal server error").model_dump(),
    )
