from pydantic import BaseModel, Field
from typing import Dict, List, Optional

class PeerAnswer(BaseModel):
    """Individual peer answer for a specific prompt"""
    name: str = Field(..., description="Name of the team member")
    avatar: str = Field(..., description="URL to the team member's avatar image")
    answer: str = Field(..., description="The team member's answer to the prompt")
    user_id: Optional[str] = Field(None, description="Optional user public ID for future use")

    class Config:
        validate_by_name = True
        from_attributes = True
        json_schema_extra = {
            "example": {
                "name": "Alex Chen",
                "avatar": "/placeholder.svg?height=100&width=100",
                "answer": "I can turn complex problems into simple, actionable steps.",
                "user_id": "user_123abc"
            }
        }

class PeerDataResponse(BaseModel):
    """Response model for peer data grouped by prompt"""
    peer_data: Dict[str, List[PeerAnswer]] = Field(
        ..., 
        description="Dictionary mapping prompt questions to lists of peer answers"
    )
    team_id: Optional[str] = Field(None, description="Team public ID for reference")
    total_prompts: Optional[int] = Field(None, description="Total number of prompts with answers")
    total_members: Optional[int] = Field(None, description="Total number of team members who answered")

    class Config:
        validate_by_name = True
        from_attributes = True
        json_schema_extra = {
            "example": {
                "peer_data": {
                    "What's your superpower at work?": [
                        {
                            "name": "Alex Chen",
                            "avatar": "/placeholder.svg?height=100&width=100",
                            "answer": "I can turn complex problems into simple, actionable steps."
                        }
                    ]
                },
                "team_id": "team_123abc",
                "total_prompts": 4,
                "total_members": 8
            }
        }
