from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from database import Base
from sqlalchemy import Boolean
from utils.short_id import generate_short_id

class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, index=True)
    public_id = Column(String(10), unique=True, index=True, nullable=False)
    organization_name = Column(String, nullable=False)
    company_logo_url = Column(String, nullable=True)  # Path or URL to the uploaded logo
    color_scheme = Column(String, nullable=False)
    color_scheme_data = Column(JSONB, nullable=True)  # Store the full color scheme object
    slack_settings = Column(JSONB, nullable=True)  # Store Slack integration settings (workspace ID, etc.)
    security_settings = Column(JSONB, nullable=True)  # Store security-related settings (e.g., allowed email domains)
    is_draft = Column(Boolean, nullable=False, default=True, server_default='1')  # True for draft/pre-signup, False for finalized

    users = relationship("WelcomepageUser", back_populates="team")

    
    def to_dict(self):
        return {
            "id": self.id,
            "public_id": self.public_id,
            "organization_name": self.organization_name,
            "company_logo_url": self.company_logo_url,
            "color_scheme": self.color_scheme,
            "color_scheme_data": self.color_scheme_data,
            "slack_settings": self.slack_settings,
            "security_settings": self.security_settings,
        }
