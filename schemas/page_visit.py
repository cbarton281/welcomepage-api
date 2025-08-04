from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class VisitLocationData(BaseModel):
    country: Optional[str] = None
    region: Optional[str] = None  
    city: Optional[str] = None


class RecordVisitRequest(BaseModel):
    visited_user_public_id: str
    referrer: Optional[str] = None
    session_id: Optional[str] = None
    real_client_ip: Optional[str] = None  # Real client IP from Next.js (bypasses infrastructure)


class UpdateVisitDurationRequest(BaseModel):
    visit_id: int
    duration_seconds: int


class PageVisitResponse(BaseModel):
    id: int
    visited_user_id: int
    visitor_public_id: Optional[str] = None
    visitor_ip_hash: Optional[str] = None
    visit_start_time: datetime
    visit_end_time: Optional[datetime] = None
    visit_duration_seconds: Optional[int] = None
    visitor_country: Optional[str] = None
    visitor_region: Optional[str] = None
    visitor_city: Optional[str] = None
    referrer: Optional[str] = None
    user_agent_hash: Optional[str] = None
    session_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class VisitStatsResponse(BaseModel):
    unique_visits: int
    total_visits: int
    avg_duration_seconds: Optional[float] = None
    countries_reached: int
    recent_visitors: list[str] = []  # List of visitor public_ids or "Anonymous"
