from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime


class SlackInstallationData(BaseModel):
    """Schema for Slack installation data stored in team.slack_settings"""
    app_id: Optional[str] = None
    enterprise_id: Optional[str] = None
    enterprise_name: Optional[str] = None
    enterprise_url: Optional[str] = None
    team_id: str
    team_name: str
    bot_token: str
    bot_id: Optional[str] = None
    bot_user_id: Optional[str] = None
    bot_scopes: Optional[str] = None
    user_id: str
    user_token: Optional[str] = None
    user_scopes: Optional[str] = None
    incoming_webhook_url: Optional[str] = None
    incoming_webhook_channel: Optional[str] = None
    incoming_webhook_channel_id: Optional[str] = None
    incoming_webhook_configuration_url: Optional[str] = None
    is_enterprise_install: Optional[bool] = False
    token_type: Optional[str] = None
    installed_at: Optional[datetime] = None
    installer_user_id: Optional[str] = None


class SlackOAuthStartResponse(BaseModel):
    """Response for OAuth start endpoint"""
    authorize_url: str
    state: str


class SlackOAuthCallbackRequest(BaseModel):
    """Request data for OAuth callback"""
    code: str
    state: str
    error: Optional[str] = None


class SlackInstallationResponse(BaseModel):
    """Response for successful Slack installation"""
    success: bool
    message: str
    team_id: Optional[str] = None
    team_name: Optional[str] = None
    enterprise_id: Optional[str] = None
    enterprise_name: Optional[str] = None


class SlackStateStoreResponse(BaseModel):
    """Response for state store operations"""
    id: int
    state: str
    created_at: datetime
    expires_at: datetime
    consumed: bool
