from sqlalchemy import Column, Integer, String, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import relationship
from database import Base

class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, index=True)
    organization_name = Column(String, nullable=False)
    company_logo = Column(String, nullable=True)  # Path or URL to the uploaded logo
    color_scheme = Column(String, nullable=False)
    company_name_blob_url = Column(String, nullable=True)  # Vercel blob URL for company name
    color_scheme_data = Column(JSON, nullable=True)  # Store the full color scheme object

    users = relationship("WelcomepageUser", back_populates="team")

