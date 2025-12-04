from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.sql import func
from database import Base
import uuid
from datetime import datetime, timedelta
from typing import Optional


class SlackStateStore(Base):
    __tablename__ = "slack_state_store"
    __table_args__ = {'schema': 'welcomepage'}

    id = Column(Integer, primary_key=True, index=True)
    state = Column(String(255), unique=True, index=True, nullable=False)
    team_public_id = Column(String(10), nullable=False)  # Store the team that initiated OAuth
    initiator_public_user_id = Column(String(10), nullable=True)  # User who initiated OAuth from app
    created_at = Column(DateTime, default=func.now(), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    consumed = Column(Boolean, default=False, nullable=False)

    def __init__(self, team_public_id: str, initiator_public_user_id: Optional[str] = None, expiration_seconds=300):
        self.state = str(uuid.uuid4())
        self.team_public_id = team_public_id
        self.initiator_public_user_id = initiator_public_user_id
        self.created_at = datetime.utcnow()
        self.expires_at = self.created_at + timedelta(seconds=expiration_seconds)
        self.consumed = False

    def is_valid(self):
        """Check if the state is still valid (not expired and not consumed)"""
        return not self.consumed and datetime.utcnow() < self.expires_at

    def consume(self):
        """Mark the state as consumed"""
        self.consumed = True

    def to_dict(self):
        return {
            "id": self.id,
            "state": self.state,
            "team_public_id": self.team_public_id,
            "initiator_public_user_id": self.initiator_public_user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "consumed": self.consumed,
        }
