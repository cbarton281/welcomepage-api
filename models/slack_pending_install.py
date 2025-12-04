from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from database import Base
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any


class SlackPendingInstall(Base):
    __tablename__ = "slack_pending_installs"
    __table_args__ = {'schema': 'welcomepage'}

    id = Column(Integer, primary_key=True, index=True)
    nonce = Column(String(255), unique=True, index=True, nullable=False)
    slack_team_id = Column(String(32), nullable=True)
    slack_team_name = Column(String(255), nullable=True)
    slack_user_id = Column(String(32), nullable=True)
    installation_json = Column(JSONB, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    consumed = Column(Boolean, default=False, nullable=False)

    def __init__(self, installation_json: Dict[str, Any], slack_team_id: Optional[str], slack_team_name: Optional[str], slack_user_id: Optional[str], expiration_seconds: int = 600):
        self.nonce = str(uuid.uuid4())
        self.slack_team_id = slack_team_id
        self.slack_team_name = slack_team_name
        self.slack_user_id = slack_user_id
        self.installation_json = installation_json
        now = datetime.utcnow()
        self.created_at = now
        self.expires_at = now + timedelta(seconds=expiration_seconds)
        self.consumed = False

    def is_valid(self) -> bool:
        return not self.consumed and datetime.utcnow() < self.expires_at

    def consume(self):
        self.consumed = True
