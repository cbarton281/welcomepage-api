from sqlalchemy import Column, Integer, String, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import relationship
from database import Base
import uuid

class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, index=True)
    public_id = Column(String(36), unique=True, index=True, default=lambda: str(uuid.uuid4()), nullable=False)
    organization_name = Column(String, nullable=False)
    company_logo_url = Column(String, nullable=True)  # Path or URL to the uploaded logo
    color_scheme = Column(String, nullable=False)
    color_scheme_data = Column(JSON, nullable=True)  # Store the full color scheme object

    users = relationship("WelcomepageUser", back_populates="team")

    
    def to_dict(self):
        return {
            "id": self.id,
            "public_id": self.public_id,
            "organization_name": self.organization_name,
            "company_logo_url": self.company_logo_url,
            "color_scheme": self.color_scheme,
            "color_scheme_data": self.color_scheme_data,
        }

