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

    class Config:
        from_attributes = True
