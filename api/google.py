from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import os
import requests

from utils.jwt_auth import require_roles
from utils.logger_factory import new_logger

router = APIRouter()

GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")


class PlacesSearchRequest(BaseModel):
    query: str


class PlaceResult(BaseModel):
    placeId: str
    name: Optional[str]
    address: Optional[str]
    lat: float
    lng: float


class PlacesSearchResponse(BaseModel):
    results: List[PlaceResult]


@router.post("/google/places/search", response_model=PlacesSearchResponse, dependencies=[Depends(require_roles('USER', 'ADMIN', 'PRE_SIGNUP'))])
def google_places_search(payload: PlacesSearchRequest):
    log = new_logger("google.places.search")

    if not GOOGLE_MAPS_API_KEY:
        log.error("Missing GOOGLE_MAPS_API_KEY")
        raise HTTPException(status_code=500, detail="Google Maps API key is not configured")

    query = (payload.query or "").strip()
    if len(query) < 3:
        raise HTTPException(status_code=400, detail="Query must be at least 3 characters")

    try:
        params = {
            "query": query,
            "key": GOOGLE_MAPS_API_KEY,
        }
        url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        r = requests.get(url, params=params, timeout=10)

        if not r.ok:
            log.error(f"Google Places HTTP error {r.status_code}: {r.text}")
            raise HTTPException(status_code=502, detail=f"Google Places HTTP error: {r.status_code}")

        data = r.json()
        status_text = data.get("status")
        if status_text not in ("OK", "ZERO_RESULTS"):
            log.error(f"Google Places API status {status_text}: {data.get('error_message')}")
            raise HTTPException(status_code=502, detail="Google Places API error")

        results = []
        log.info(f"Google Places status={status_text}, results_count={len(data.get('results') or [])}")
        for place in (data.get("results") or [])[:3]:
            geometry = (place.get("geometry") or {}).get("location") or {}
            # Defensive parsing, ensure lat/lng present
            if geometry.get("lat") is None or geometry.get("lng") is None:
                continue
            results.append(PlaceResult(
                placeId=place.get("place_id"),
                name=place.get("name"),
                address=place.get("formatted_address"),
                lat=float(geometry.get("lat")),
                lng=float(geometry.get("lng")),
            ))

        return PlacesSearchResponse(results=results)

    except HTTPException:
        raise
    except Exception:
        log.exception("Unexpected error during Google Places search")
        raise HTTPException(status_code=500, detail="Failed to search locations")
