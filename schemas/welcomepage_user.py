from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class FileMeta(BaseModel):
    filename: str
    contentType: str
    size: int

class HandwaveEmoji(BaseModel):
    emoji: str
    label: str

class AnswerImage(BaseModel):
    filename: str
    contentType: str
    size: int

class Answer(BaseModel):
    text: str
    image: Optional[AnswerImage] = None
    specialData: Optional[Any] = None

class TeamSettings(BaseModel):
    organizationName: Optional[str] = None
    hasLogo: Optional[bool] = None
    colorScheme: Optional[str] = None
    logoData: Optional[str] = None

class WelcomepageUserDTO(BaseModel):
    id: Optional[int] = None
    name: str
    role: str
    location: str
    nickname: Optional[str] = None
    greeting: str
    handwaveEmoji: Optional[HandwaveEmoji] = None
    handwaveEmojiUrl: Optional[str] = None
    profilePhoto: Optional[FileMeta] = None
    profilePhotoUrl: Optional[str] = None
    waveGif: Optional[FileMeta] = None
    waveGifUrl: Optional[str] = None
    pronunciationRecording: Optional[FileMeta] = None
    pronunciationRecordingUrl: Optional[str] = None
    selectedPrompts: List[str]
    answers: Dict[str, Answer]
    teamSettings: Optional[TeamSettings] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None

    @classmethod
    def from_model(cls, user):
        return cls(**user.to_dict())
