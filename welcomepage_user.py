from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String

Base = declarative_base()

class WelcomepageUser(Base):
    __tablename__ = 'welcomepage_users'
    id = Column(Integer, primary_key=True)
    username = Column(String, nullable=False)
    email = Column(String, nullable=False)

    def __init__(self, username, email):
        self.username = username
        self.email = email

    @classmethod
    def from_dict(cls, data):
        return cls(
            username=data.get('username'),
            email=data.get('email')
        )

    def to_dict(self):
        return {'id': self.id, 'username': self.username, 'email': self.email}

from pydantic import BaseModel

class WelcomepageUserDTO(BaseModel):
    id: int | None = None
    username: str
    email: str

    @classmethod
    def from_model(cls, user: WelcomepageUser):
        return cls(id=user.id, username=user.username, email=user.email)
