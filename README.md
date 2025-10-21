# Instagram Scraper Service

> ⚠️ **Disclaimer**: Automated scraping may violate Instagram's Terms of Service and regional laws. Deploy this code only where you have the right to collect the data.

## Requirements

- Docker & Docker Compose
- NordVPN SOCKS5 credentials (manual setup panel)
- Instagram account (optional, enables higher-quality data)

## Setup

```bash
cp .env.example .env
# edit .env with NordVPN + (optionally) Instagram details
```

Main environment variables:

| Key | Description |
| --- | --- |
| `API_AUTH_KEY` | Required header value for `X-API-Key` (blank disables auth). |
| `NORD_VPN_USERNAME` / `NORD_VPN_PASSWORD` | NordVPN SOCKS credentials. |
| `NORD_PROXY_POOL` | Comma list of SOCKS5 hosts (e.g. `ch465.nordvpn.com`). |
| `INSTAGRAM_USERNAME` / `INSTAGRAM_PASSWORD` | Lets the service log in headlessly and cache cookies in `/data/instagram_cookies.json`. |

## Run

```bash
docker compose up --build
```

The service listens on `http://localhost:8000` (FastAPI docs at `/docs`).

## Example

```bash
curl -H "X-API-Key: $API_AUTH" \
     http://localhost:8000/instagram/pewdiepie | jq
```

Successful responses look like:

```json
{
  "data": {
    "username": "pewdiepie",
    "followers": 20292783,
    "profile_picture_url": "https://scontent...",
    "profile_image_path": "/data/images/pewdiepie_20251021190313.jpg",
    "is_cached": false,
    "scraped_at": "2025-10-21T19:03:13.206772Z"
  }
}
```

All snapshots and images are stored under `data/` (ignored by git).

## License

Licensed under the Apache 2.0 License. Contributions welcome. #kevinzingg.ch
