from sqlalchemy import Column, Integer, String, Text, JSON
import json
from database import Base

from sqlalchemy.orm import relationship

class WelcomepageUser(Base):
    __tablename__ = 'welcomepage_users'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False)
    location = Column(String, nullable=False)
    nickname = Column(String)
    greeting = Column(String, nullable=False)
    handwave_emoji_url = Column(String)
    profile_photo_url = Column(String)
    wave_gif_url = Column(String)
    pronunciation_recording_url = Column(String)
    selected_prompts = Column(JSON, nullable=False)  # list of strings
    answers = Column(JSON, nullable=False)  # dict
    team_settings = Column(JSON)
    created_at = Column(String)
    updated_at = Column(String)
    team_id = Column(Integer, ForeignKey('teams.id'))

    team = relationship("Team", back_populates="users")

    def __init__(self, **kwargs):
        for field in kwargs:
            setattr(self, field, kwargs[field])

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'role': self.role,
            'location': self.location,
            'nickname': self.nickname,
            'greeting': self.greeting,
            'handwaveEmojiUrl': self.handwave_emoji_url,
            'profilePhotoUrl': self.profile_photo_url,
            'waveGifUrl': self.wave_gif_url,
            'pronunciationRecordingUrl': self.pronunciation_recording_url,
            'selectedPrompts': self.selected_prompts,
            'answers': self.answers,
            'teamSettings': self.team_settings,
            'createdAt': self.created_at,
            'updatedAt': self.updated_at,
        }
