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
    sharing_settings = Column(JSONB, nullable=True)  # Store sharing settings (enabled, uuid, expires_at)
    is_draft = Column(Boolean, nullable=False, default=True, server_default='1')  # True for draft/pre-signup, False for finalized
    
    # Stripe integration fields
    stripe_customer_id = Column(String(255), nullable=True, unique=True, index=True)  # Stripe customer ID
    stripe_subscription_id = Column(String(255), nullable=True, unique=True, index=True)  # Active subscription ID
    stripe_subscription_status = Column(String(50), nullable=True)  # Raw Stripe status: 'active', 'past_due', 'canceled', etc.
    subscription_status = Column(String(50), nullable=True)  # Standardized: 'pro' or 'free' only

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
            "sharing_settings": self.sharing_settings,
            "stripe_customer_id": self.stripe_customer_id,
            "stripe_subscription_id": self.stripe_subscription_id,
            "subscription_status": self.subscription_status,
        }
