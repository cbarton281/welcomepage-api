from pydantic import BaseModel, Field, field_serializer, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime

class FileMeta(BaseModel):
    filename: str
    content_type: str = Field(..., alias="contentType")
    size: int

    class Config:
        validate_by_name = True
        from_attributes = True

class HandwaveEmoji(BaseModel):
    emoji: str
    label: str

    class Config:
        validate_by_name = True
        from_attributes = True

class AnswerImage(BaseModel):
    filename: str
    content_type: str = Field(..., alias="contentType")
    size: int
    url: str

    class Config:
        validate_by_name = True
        from_attributes = True

class Reaction(BaseModel):
    emoji: str
    user: str
    user_id: str = Field(alias="userId")
    timestamp: Optional[str] = None
    id: str

    class Config:
        validate_by_name = True
        from_attributes = True

class Answer(BaseModel):
    text: str
    image: Optional[AnswerImage] = None
    special_data: Optional[Any] = Field(None, alias="specialData")
    reactions: Optional[List[Reaction]] = None

    class Config:
        validate_by_name = True
        from_attributes = True



class WelcomepageUserDTO(BaseModel):
    id: Optional[int] = None
    public_id: Optional[str] = Field(None, alias="publicId")
    name: str
    role: Optional[str] = None
    auth_role: Optional[str] = Field(None, alias="authRole")
    auth_email: Optional[str] = Field(None, alias="authEmail")
    location: Optional[str] = None
    nickname: Optional[str] = None
    greeting: Optional[str] = None
    hi_yall_text: Optional[str] = Field(None, alias="hiYallText")
    handwave_emoji: Optional[HandwaveEmoji] = Field(None, alias="handwaveEmoji")
    handwave_emoji_url: Optional[str] = Field(None, alias="handwaveEmojiUrl")
    profile_photo: Optional[FileMeta] = Field(None, alias="profilePhoto")
    profile_photo_url: Optional[str] = Field(None, alias="profilePhotoUrl")
    wave_gif: Optional[FileMeta] = Field(None, alias="waveGif")
    wave_gif_url: Optional[str] = Field(None, alias="waveGifUrl")
    pronunciation_recording: Optional[FileMeta] = Field(None, alias="pronunciationRecording")
    pronunciation_recording_url: Optional[str] = Field(None, alias="pronunciationRecordingUrl")
    selected_prompts: Optional[List[str]] = Field(None, alias="selectedPrompts")
    answers: Optional[Dict[str, Answer]] = None
    # Include page-level comments so clients don't need a separate fetch
    page_comments: Optional[List[Dict[str, Any]]] = Field(None, alias="pageComments")
    # Bento widgets configuration as arbitrary JSON list
    bento_widgets: Optional[List[Dict[str, Any]]] = Field(None, alias="bentoWidgets")
    team_public_id: Optional[str] = Field(None, alias="teamPublicId")
    invite_banner_dismissed: Optional[bool] = Field(None, alias="inviteBannerDismissed")

    created_at: Optional[str] = Field(None, alias="createdAt")
    updated_at: Optional[str] = Field(None, alias="updatedAt")

    @field_validator('handwave_emoji', mode='before')
    @classmethod
    def validate_handwave_emoji(cls, v):
        # Convert empty string to None for handwave_emoji
        if v == '' or v == {}:
            return None
        return v

    @field_validator('answers', mode='before')
    @classmethod
    def validate_answers(cls, v):
        # Handle answers field and sanitize image data
        if isinstance(v, dict):
            for prompt, answer in v.items():
                if isinstance(answer, dict) and 'image' in answer:
                    # Convert empty dict {} to None for image field
                    if answer['image'] == {}:
                        answer['image'] = None
        return v

    @field_validator('created_at', mode='before')
    @classmethod
    def validate_created_at(cls, v):
        # Convert datetime objects to ISO strings
        if isinstance(v, datetime):
            return v.isoformat()
        return v

    @field_validator('updated_at', mode='before')
    @classmethod
    def validate_updated_at(cls, v):
        # Convert datetime objects to ISO strings
        if isinstance(v, datetime):
            return v.isoformat()
        return v

    @field_serializer('created_at')
    def serialize_created_at(self, value):
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    @field_serializer('updated_at')
    def serialize_updated_at(self, value):
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    class Config:
        validate_by_name = True
        from_attributes = True
