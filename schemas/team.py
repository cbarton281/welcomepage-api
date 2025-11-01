from pydantic import BaseModel
from typing import Optional

from typing import Optional, Dict, Any

class TeamCreate(BaseModel):
    organization_name: str
    color_scheme: str
    color_scheme_data: Optional[Dict[str, Any]] = None
    slack_settings: Optional[Dict[str, Any]] = None

class TeamRead(TeamCreate):
    id: int
    public_id: str  # Public-facing unique identifier
    company_logo_url: Optional[str]
    color_scheme_data: Optional[Dict[str, Any]] = None
    slack_settings: Optional[Dict[str, Any]] = None
    security_settings: Optional[Dict[str, Any]] = None
    sharing_settings: Optional[Dict[str, Any]] = None
    is_draft: bool
    # Stripe integration fields
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    stripe_subscription_status: Optional[str] = None  # Raw Stripe status
    subscription_status: Optional[str] = None  # Simplified: "free" or "pro"
    published_count: Optional[int] = None  # Number of published pages for this team

    class Config:
        from_attributes = True
