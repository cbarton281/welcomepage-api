from pydantic import BaseModel
from typing import Optional

class WelcomepageUserDTO(BaseModel):
    id: Optional[int] = None
    username: str
    email: str

    @classmethod
    def from_model(cls, user):
        return cls(id=user.id, username=user.username, email=user.email)
