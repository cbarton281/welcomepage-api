from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from database import Base
from sqlalchemy.orm import relationship
from sqlalchemy import ForeignKey
from sqlalchemy import Boolean
from sqlalchemy.sql import func
from utils.short_id import generate_short_id


class WelcomepageUser(Base):
    __tablename__ = 'welcomepage_users'
    id = Column(Integer, primary_key=True)
    public_id = Column(String(10), unique=True, index=True,nullable=False)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False)
    location = Column(String, nullable=False)
    nickname = Column(String)
    greeting = Column(String, nullable=False)
    hi_yall_text = Column(String)
    handwave_emoji = Column(JSONB)
    handwave_emoji_url = Column(String)
    profile_photo_url = Column(String)
    wave_gif_url = Column(String)
    pronunciation_text = Column(String)
    pronunciation_recording_url = Column(String)
    selected_prompts = Column(JSONB, nullable=False)  # list of strings
    answers = Column(JSONB, nullable=False)  # dict
    # New: page-level comments stored as JSON array
    page_comments = Column(JSONB, nullable=True)
    # New: Bento widgets configuration stored as JSON array
    bento_widgets = Column(JSONB, nullable=True)
    # UI preferences/flags
    invite_banner_dismissed = Column(Boolean, nullable=False, default=False, server_default='0')

    created_at = Column(DateTime, nullable=False, default=func.now(), server_default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), server_default=func.now(), onupdate=func.now())
    team_id = Column(Integer, ForeignKey('teams.id'))
    is_draft = Column(Boolean, nullable=False, default=True, server_default='1')  # True for draft/pre-signup, False for finalized
    auth_role = Column(String(32), nullable=True)  # Authorization role (admin, user, pre-signup, etc)
    auth_email = Column(String(256), nullable=True)  # Authorization email, distinct from profile email
    slack_user_id = Column(String(32), nullable=True)  # Slack user ID for integration
    # Page sharing settings
    is_shareable = Column(Boolean, nullable=False, default=False, server_default='0')  # Whether page is publicly shareable
    share_uuid = Column(String(25), nullable=True, unique=True, index=True)  # 25-character UUID for sharing

    team = relationship("Team", back_populates="users")

    def __init__(self, **kwargs):
        for field in kwargs:
            setattr(self, field, kwargs[field])
        if 'public_id' not in kwargs or not getattr(self, 'public_id', None):
            self.public_id = generate_short_id()

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
            'slack_user_id': self.slack_user_id,
            'location': self.location,
            'nickname': self.nickname,
            'greeting': self.greeting,
            'hi_yall_text': self.hi_yall_text,
            'handwaveEmoji': self.handwave_emoji,
            'handwaveEmojiUrl': self.handwave_emoji_url,
            'profilePhotoUrl': self.profile_photo_url,
            'waveGifUrl': self.wave_gif_url,
            'pronunciationText': self.pronunciation_text,
            'pronunciationRecordingUrl': self.pronunciation_recording_url,
            'selectedPrompts': self.selected_prompts,
            'answers': self.answers,
            'pageComments': self.page_comments,
            'bentoWidgets': self.bento_widgets,
            'inviteBannerDismissed': self.invite_banner_dismissed,
            'team_id': self.team_id,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
            'isDraft': self.is_draft,
            'isShareable': self.is_shareable,
            'shareUuid': self.share_uuid,
        }
