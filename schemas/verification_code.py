from pydantic import BaseModel
from typing import Optional

class VerificationResponse(BaseModel):
    success: bool
    public_id: Optional[str]
    auth_role: Optional[str]
