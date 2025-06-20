from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class FileMeta(BaseModel):
    filename: str
    content_type: str = Field(..., alias="contentType")
    size: int

    class Config:
        allow_population_by_field_name = True
        orm_mode = True

class HandwaveEmoji(BaseModel):
    emoji: str
    label: str

    class Config:
        allow_population_by_field_name = True
        orm_mode = True

class AnswerImage(BaseModel):
    filename: str
    content_type: str = Field(..., alias="contentType")
    size: int

    class Config:
        allow_population_by_field_name = True
        orm_mode = True

class Answer(BaseModel):
    text: str
    image: Optional[AnswerImage] = None
    special_data: Optional[Any] = Field(None, alias="specialData")

    class Config:
        allow_population_by_field_name = True
        orm_mode = True

class TeamSettings(BaseModel):
    organization_name: Optional[str] = Field(None, alias="organizationName")
    has_logo: Optional[bool] = Field(None, alias="hasLogo")
    color_scheme: Optional[str] = Field(None, alias="colorScheme")
    logo_data: Optional[str] = Field(None, alias="logoData")

    class Config:
        allow_population_by_field_name = True
        orm_mode = True

class WelcomepageUserDTO(BaseModel):
    id: Optional[int] = None
    name: str
    role: str
    location: str
    nickname: Optional[str] = None
    greeting: str
    handwave_emoji: Optional[HandwaveEmoji] = Field(None, alias="handwaveEmoji")
    handwave_emoji_url: Optional[str] = Field(None, alias="handwaveEmojiUrl")
    profile_photo: Optional[FileMeta] = Field(None, alias="profilePhoto")
    profile_photo_url: Optional[str] = Field(None, alias="profilePhotoUrl")
    wave_gif: Optional[FileMeta] = Field(None, alias="waveGif")
    wave_gif_url: Optional[str] = Field(None, alias="waveGifUrl")
    pronunciation_recording: Optional[FileMeta] = Field(None, alias="pronunciationRecording")
    pronunciation_recording_url: Optional[str] = Field(None, alias="pronunciationRecordingUrl")
    selected_prompts: List[str] = Field(..., alias="selectedPrompts")
    answers: Dict[str, Answer]
    team_settings: Optional[TeamSettings] = Field(None, alias="teamSettings")
    created_at: Optional[str] = Field(None, alias="createdAt")
    updated_at: Optional[str] = Field(None, alias="updatedAt")

    @classmethod
    def from_model(cls, user):
        return cls(**user.to_dict())

    class Config:
        allow_population_by_field_name = True
        orm_mode = True
