from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
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
    name: Optional[str] = None
    address: Optional[str] = None
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


class GeoSuggestResponse(BaseModel):
    suggestion: str
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


def _extract_client_ip(request: Request) -> Optional[str]:
    """Best-effort extraction of the client IP, accounting for proxies.
    Priority: X-Forwarded-For (first), CF-Connecting-IP, X-Real-IP, request.client.host
    """
    xff = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[0]
    cf = request.headers.get("cf-connecting-ip") or request.headers.get("CF-Connecting-IP")
    if cf:
        return cf.strip()
    xr = request.headers.get("x-real-ip") or request.headers.get("X-Real-IP")
    if xr:
        return xr.strip()
    if request.client and request.client.host:
        return request.client.host
    return None


@router.get(
    "/google/geo/suggest-location",
    response_model=GeoSuggestResponse,
    dependencies=[Depends(require_roles('USER', 'ADMIN', 'PRE_SIGNUP'))],
)
async def suggest_location_from_ip(request: Request) -> GeoSuggestResponse:
    """Suggest a human-friendly location string based on requester IP.
    Uses ipapi.co (HTTPS, no key) to resolve an approximate city/region/country and coordinates.
    Returns a suggestion suitable as an initial Google Maps search string.
    """
    log = new_logger("google.geo.suggest")
    ip = _extract_client_ip(request)

    default = GeoSuggestResponse(
        suggestion="Toronto, ON, Canada",
        city="Toronto",
        region="Ontario",
        country="Canada",
        lat=43.6532,
        lng=-79.3832,
    )

    if not ip or ip in ("127.0.0.1", "::1"):
        log.info(f"No resolvable client IP (ip={ip}). Returning default: Toronto")
        return default

    try:
        url = f"https://ipapi.co/{ip}/json/"
        r = requests.get(url, timeout=5)
        if not r.ok:
            log.warning(f"ipapi.co HTTP {r.status_code} for ip={ip}: {r.text[:300]}")
            return default
        data: Dict[str, Any] = r.json() or {}
        if data.get("error"):
            log.warning(f"ipapi.co error for ip={ip}: {data.get('reason')}")
            return default

        city = (data.get("city") or "").strip() or None
        region = (data.get("region") or "").strip() or None
        country = (data.get("country_name") or "").strip() or None
        lat = data.get("latitude")
        lon = data.get("longitude")

        parts = [p for p in [city, region, country] if p]
        suggestion = ", ".join(parts) if parts else None
        if not suggestion:
            log.info(f"ipapi.co returned no usable location fields for ip={ip}. Falling back to default")
            return default

        lat_f = float(lat) if lat is not None else None
        lon_f = float(lon) if lon is not None else None

        log.info(f"Geo suggestion for ip={ip}: {suggestion} (lat={lat_f}, lon={lon_f})")
        return GeoSuggestResponse(
            suggestion=suggestion,
            city=city,
            region=region,
            country=country,
            lat=lat_f,
            lng=lon_f,
        )

    except Exception:
        log.exception(f"Unexpected error during IP geolocation for ip={ip}")
        return default
