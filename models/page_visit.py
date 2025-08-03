from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from database import Base


class PageVisit(Base):
    __tablename__ = 'page_visits'
    
    id = Column(Integer, primary_key=True)
    visited_user_id = Column(Integer, nullable=False)  # Reference to visited user ID
    visitor_public_id = Column(String(10), nullable=False)  # Reference to visitor public_id (always authenticated)
    visit_start_time = Column(DateTime, nullable=False, default=func.now(), server_default=func.now())
    visit_end_time = Column(DateTime, nullable=True)
    visit_duration_seconds = Column(Integer, nullable=True)
    visitor_country = Column(String(2), nullable=True)  # ISO country code
    visitor_region = Column(String(100), nullable=True)  # State/Province
    visitor_city = Column(String(100), nullable=True)    # City name
    referrer = Column(String(512), nullable=True)
    user_agent = Column(String(512), nullable=True)  # Store user agent for analytics (no need to hash)
    session_id = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=func.now(), server_default=func.now())
    
    # No foreign key constraints - preserves visit history when users are deleted
    # All visitors are authenticated users with public_id
    
    def to_dict(self):
        return {
            'id': self.id,
            'visited_user_id': self.visited_user_id,
            'visitor_public_id': self.visitor_public_id,
            'user_agent': self.user_agent,
            'visit_start_time': self.visit_start_time.isoformat() if self.visit_start_time else None,
            'visit_end_time': self.visit_end_time.isoformat() if self.visit_end_time else None,
            'visit_duration_seconds': self.visit_duration_seconds,
            'visitor_country': self.visitor_country,
            'visitor_region': self.visitor_region,
            'visitor_city': self.visitor_city,
            'referrer': self.referrer,
            'session_id': self.session_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
