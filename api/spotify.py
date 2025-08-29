from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional, Literal
import os
import base64
import requests

from utils.jwt_auth import require_roles
from utils.logger_factory import new_logger

router = APIRouter()

SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET")

if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
    # Do not raise at import time to avoid breaking unrelated endpoints on startup.
    # We'll validate on request and return a clear 500 with message.
    pass


class ResolveRequest(BaseModel):
    url: str


class SpotifyData(BaseModel):
    url: str
    name: Optional[str] = None
    image: Optional[str] = None
    type: Optional[Literal['playlist', 'podcast', 'track']] = None
    description: Optional[str] = None
    owner: Optional[str] = None
    publisher: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    trackCount: Optional[int] = None
    episodeCount: Optional[int] = None
    duration: Optional[int] = None


def _extract_type_and_id(url: str):
    """
    Supports URLs like:
    - https://open.spotify.com/playlist/{id}
    - https://open.spotify.com/show/{id}
    - https://open.spotify.com/track/{id}
    Also supports regional subpaths or query params.
    Returns (api_type, id) where api_type in ['playlists', 'shows', 'tracks']
    """
    try:
        # Normalize
        if 'spotify.com' not in url:
            return None, None
        # Split by '/'
        parts = url.split('?')[0].split('#')[0].strip('/').split('/')
        # Find indices for 'playlist' | 'show' | 'track'
        api_map = {
            'playlist': 'playlists',
            'show': 'shows',
            'track': 'tracks',
        }
        for i, p in enumerate(parts):
            if p in api_map and i + 1 < len(parts):
                return api_map[p], parts[i + 1]
        return None, None
    except Exception:
        return None, None


def _get_client_credentials_token(log):
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        log.error("Missing SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_SECRET")
        raise HTTPException(status_code=500, detail="Spotify credentials are not configured")

    token_url = 'https://accounts.spotify.com/api/token'
    basic = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
    headers = {
        'Authorization': f'Basic {basic}',
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    data = {'grant_type': 'client_credentials'}
    resp = requests.post(token_url, headers=headers, data=data, timeout=10)
    if not resp.ok:
        raise HTTPException(status_code=502, detail=f"Spotify token error: {resp.status_code}")
    return resp.json().get('access_token')


@router.post("/spotify/resolve", dependencies=[Depends(require_roles('USER', 'ADMIN', 'PRE_SIGNUP'))])
def resolve_spotify_url(payload: ResolveRequest):
    log = new_logger("spotify.resolve")
    log.info(f"Resolve request: url={payload.url}")

    api_type, item_id = _extract_type_and_id(payload.url)
    if not api_type or not item_id:
        raise HTTPException(status_code=400, detail="Invalid or unsupported Spotify URL")

    token = _get_client_credentials_token(log)

    endpoint = f"https://api.spotify.com/v1/{api_type}/{item_id}"
    headers = { 'Authorization': f'Bearer {token}' }

    r = requests.get(endpoint, headers=headers, timeout=10)
    if not r.ok:
        log.error(f"Spotify API error {r.status_code}: {r.text}")
        raise HTTPException(status_code=502, detail=f"Spotify API error: {r.status_code}")

    data = r.json()

    # Map response
    if api_type == 'playlists':
        mapped = SpotifyData(
            url=f"https://open.spotify.com/playlist/{item_id}",
            name=data.get('name'),
            image=(data.get('images') or [{}])[0].get('url'),
            type='playlist',
            description=data.get('description'),
            owner=((data.get('owner') or {}).get('display_name')),
            trackCount=((data.get('tracks') or {}).get('total')),
        )
    elif api_type == 'shows':
        mapped = SpotifyData(
            url=f"https://open.spotify.com/show/{item_id}",
            name=data.get('name'),
            image=(data.get('images') or [{}])[0].get('url'),
            type='podcast',
            description=data.get('description'),
            publisher=data.get('publisher'),
            episodeCount=data.get('total_episodes'),
        )
    elif api_type == 'tracks':
        album = data.get('album') or {}
        artists = data.get('artists') or []
        mapped = SpotifyData(
            url=f"https://open.spotify.com/track/{item_id}",
            name=data.get('name'),
            image=(album.get('images') or [{}])[0].get('url'),
            type='track',
            artist=(artists[0].get('name') if artists else None),
            album=album.get('name'),
            duration=data.get('duration_ms'),
        )
    else:
        raise HTTPException(status_code=400, detail="Unsupported Spotify content type")

    log.info("Resolved successfully")
    return mapped.dict()
