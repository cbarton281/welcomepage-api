from sqlalchemy import Column, Integer, String, JSON, DateTime
from database import Base
from sqlalchemy.orm import relationship
from sqlalchemy import ForeignKey
from sqlalchemy import Boolean
from sqlalchemy.sql import func
import uuid


class WelcomepageUser(Base):
    __tablename__ = 'welcomepage_users'
    id = Column(Integer, primary_key=True)
    public_id = Column(String(36), unique=True, index=True, default=lambda: str(uuid.uuid4()), nullable=False)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False)
    location = Column(String, nullable=False)
    nickname = Column(String)
    greeting = Column(String, nullable=False)
    hi_yall_text = Column(String)
    handwave_emoji_url = Column(String)
    profile_photo_url = Column(String)
    wave_gif_url = Column(String)
    pronunciation_recording_url = Column(String)
    selected_prompts = Column(JSON, nullable=False)  # list of strings
    answers = Column(JSON, nullable=False)  # dict
    team_settings = Column(JSON)
    created_at = Column(DateTime, nullable=False, default=func.now(), server_default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), server_default=func.now(), onupdate=func.now())
    team_id = Column(Integer, ForeignKey('teams.id'))
    is_draft = Column(Boolean, nullable=False, default=True, server_default='1')  # True for draft/pre-signup, False for finalized
    auth_role = Column(String(32), nullable=True)  # Authorization role (admin, user, pre-signup, etc)
    auth_email = Column(String(256), nullable=True)  # Authorization email, distinct from profile email

    team = relationship("Team", back_populates="users")

    def __init__(self, **kwargs):
        for field in kwargs:
            setattr(self, field, kwargs[field])
        if 'public_id' not in kwargs or not getattr(self, 'public_id', None):
            self.public_id = str(uuid.uuid4())

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    def to_dict(self):
        return {
            'id': self.id,
            'public_id': self.public_id,
            'name': self.name,
            'role': self.role,
            'auth_role': self.auth_role,
            'auth_email': self.auth_email,
            'location': self.location,
            'nickname': self.nickname,
            'greeting': self.greeting,
            'hi_yall_text': self.hi_yall_text,
            'handwaveEmojiUrl': self.handwave_emoji_url,
            'profilePhotoUrl': self.profile_photo_url,
            'waveGifUrl': self.wave_gif_url,
            'pronunciationRecordingUrl': self.pronunciation_recording_url,
            'selectedPrompts': self.selected_prompts,
            'answers': self.answers,
            'teamSettings': self.team_settings,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
        }
