from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


class PublishWelcomepageRequest(BaseModel):
    """Request schema for publishing a welcomepage to Slack"""
    user_public_id: str = Field(..., description="Public ID of the user whose welcomepage to publish")
    custom_message: Optional[str] = Field("", description="Optional custom message from the user")


class SlackMessageResponse(BaseModel):
    """Response schema for Slack message details"""
    channel: str = Field(..., description="Slack channel ID where message was posted")
    timestamp: str = Field(..., description="Slack message timestamp")
    message_url: Optional[str] = Field(None, description="Direct URL to the Slack message")


class PublishWelcomepageResponse(BaseModel):
    """Response schema for welcomepage publishing"""
    success: bool = Field(..., description="Whether the publish operation was successful")
    message: str = Field(..., description="Human-readable message about the operation")
    slack_response: Optional[SlackMessageResponse] = Field(None, description="Slack message details if successful")
    error: Optional[str] = Field(None, description="Error type if operation failed")
    slack_error: Optional[str] = Field(None, description="Specific Slack error code if applicable")


class TestChannelRequest(BaseModel):
    """Request schema for testing Slack channel connectivity"""
    channel_id: str = Field(..., description="Slack channel ID to test")


class TestChannelResponse(BaseModel):
    """Response schema for channel test results"""
    success: bool = Field(..., description="Whether the channel test was successful")
    message: str = Field(..., description="Human-readable message about the test result")
    slack_response: Optional[Dict[str, Any]] = Field(None, description="Slack response details if successful")
    error: Optional[str] = Field(None, description="Error type if test failed")
    slack_error: Optional[str] = Field(None, description="Specific Slack error code if applicable")
