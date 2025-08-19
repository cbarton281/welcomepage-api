from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
import logging
from database import get_db
from models.team import Team
from utils.logger_factory import new_logger

router = APIRouter()

slack_redirect_retry_logger = new_logger("slack_redirect_retry")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(OperationalError),
    before_sleep=before_sleep_log(slack_redirect_retry_logger, logging.WARNING),
)
def _fetch_team_by_public_id(db: Session, public_id: str):
    try:
        return db.query(Team).filter_by(public_id=public_id).first()
    except OperationalError:
        db.rollback()
        raise


@router.get("/public/slack/channel/{public_id}")
async def resolve_slack_channel_redirect(public_id: str, db: Session = Depends(get_db)):
    """
    Public resolver that generates a Slack deep link to the team's publish channel.
    Returns a redirect URL in the format: slack://channel?team=<TEAM_ID>&id=<CHANNEL_ID>
    
    This avoids exposing Slack team/channel IDs in the frontend URL.
    """
    log = new_logger("resolve_slack_channel_redirect")
    log.info(f"Resolving Slack channel redirect for team: {public_id}")

    team = _fetch_team_by_public_id(db, public_id)
    if not team:
        log.warning(f"Team not found: {public_id}")
        raise HTTPException(status_code=404, detail="Team not found")

    settings = team.slack_settings or {}
    slack_app = settings.get("slack_app") if isinstance(settings, dict) else None
    publish_channel = settings.get("publish_channel") if isinstance(settings, dict) else None

    # Validate Slack installation exists
    if not slack_app or not isinstance(slack_app, dict):
        log.warning(f"No Slack installation found for team {public_id}")
        raise HTTPException(status_code=404, detail="Slack integration not found")
    
    # Validate publish channel is configured
    if not publish_channel or not isinstance(publish_channel, dict):
        log.warning(f"No publish channel configured for team {public_id}")
        raise HTTPException(status_code=404, detail="Publish channel not configured")

    slack_team_id = slack_app.get("team_id") or slack_app.get("enterprise_id")
    channel_id = publish_channel.get("id")
    
    if not slack_team_id or not channel_id:
        log.error(f"Missing required Slack identifiers for team {public_id}: team_id={slack_team_id}, channel_id={channel_id}")
        raise HTTPException(status_code=500, detail="Slack configuration incomplete")

    # Generate Slack deep link
    slack_deep_link = f"slack://channel?team={slack_team_id}&id={channel_id}"
    
    log.info(f"Generated Slack channel deep link for team {public_id}")
    return {"redirect_url": slack_deep_link}
