from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class TeamMemberOption(BaseModel):
    """Option for a question (team member choice)"""
    id: str
    name: str
    avatar: Optional[str] = None


class QuestionEmojis(BaseModel):
    """Emojis for two-truths-lie questions"""
    truth: str
    lie1: str
    lie2: str


class Question(BaseModel):
    """Game question model"""
    id: str
    type: str  # 'guess-who' | 'who-said' | 'two-truths-lie'
    question: str
    correctAnswer: str
    correctAnswerId: str
    options: List[TeamMemberOption]
    additionalInfo: Optional[str] = None
    emojis: Optional[Dict[str, str]] = None  # For two-truths-lie: { truth: str, lie1: str, lie2: str }
    promptText: Optional[str] = None
    answerText: Optional[str] = None
    memberPublicId: Optional[str] = None  # For two-truths-lie to identify the member
    memberNickname: Optional[str] = None  # For two-truths-lie to identify the member


class TeamMemberAnswer(BaseModel):
    """Answer structure for a team member"""
    text: str
    image: Optional[Any] = None
    specialData: Optional[Any] = None
    
    class Config:
        extra = "allow"  # Allow extra fields


class TeamMember(BaseModel):
    """Team member model for game generation"""
    public_id: str
    name: str
    nickname: Optional[str] = None
    role: Optional[str] = None
    profile_image: Optional[str] = None
    wave_gif_url: Optional[str] = None
    selectedPrompts: Optional[List[str]] = None
    answers: Optional[Dict[str, Dict[str, Any]]] = None  # Flexible structure: Dict[str, {text, image?, specialData?}]
    bentoWidgets: Optional[List[Any]] = None
    
    class Config:
        extra = "allow"  # Allow extra fields for flexibility


class AlternateMember(BaseModel):
    """Minimal member data for alternate pool (distractors and animations)"""
    public_id: str
    name: str
    wave_gif_url: Optional[str] = None


class GenerateQuestionsRequest(BaseModel):
    """Request model for generating game questions"""
    members: List[TeamMember]
    alternatePool: Optional[List[AlternateMember]] = None  # Optional alternate pool for distractors


class GenerateQuestionsResponse(BaseModel):
    """Response model for generated questions"""
    questions: List[Question]


class WaveGifUrlsResponse(BaseModel):
    """Response model for wave GIF URLs for animations"""
    urls: List[str]


class AlternatePoolResponse(BaseModel):
    """Response model for alternate pool (members with minimal data)"""
    members: List[AlternateMember]

