from pydantic import BaseModel
from typing import Optional

from typing import Optional, Dict, Any

class TeamCreate(BaseModel):
    organization_name: str
    color_scheme: str
    color_scheme_data: Optional[Dict[str, Any]] = None

class TeamRead(TeamCreate):
    id: int
    company_logo: Optional[str]
    company_name_blob_url: Optional[str]
    color_scheme_data: Optional[Dict[str, Any]] = None

    class Config:
        orm_mode = True
