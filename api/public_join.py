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
import os
from database import get_db
from models.team import Team
from utils.logger_factory import new_logger

router = APIRouter()

resolve_retry_logger = new_logger("public_join_resolve_retry")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(OperationalError),
    before_sleep=before_sleep_log(resolve_retry_logger, logging.WARNING),
)
def _fetch_team_by_public_id(db: Session, public_id: str):
    try:
        return db.query(Team).filter_by(public_id=public_id).first()
    except OperationalError:
        db.rollback()
        raise


@router.get("/public/join/resolve/{public_id}")
async def resolve_join_destination(public_id: str, db: Session = Depends(get_db)):
    """
    Public resolver that determines where a join link should redirect:
    - If Slack is installed (and optionally auto_invite enabled), redirect to Slack
    - Otherwise, redirect to the web join page

    Returns a minimal JSON payload to avoid exposing sensitive details:
    { "target": "slack" | "web", "redirect_url": "https://slack.com/app_redirect?..."? }
    """
    log = new_logger("resolve_join_destination")
    log.info(f"Resolving join destination for team: {public_id}")

    team = _fetch_team_by_public_id(db, public_id)
    if not team:
        log.warning(f"Team not found: {public_id}")
        raise HTTPException(status_code=404, detail="Team not found")

    settings = team.slack_settings or {}
    slack_app = settings.get("slack_app") if isinstance(settings, dict) else None

    # Decide: Slack vs Web
    if slack_app and isinstance(slack_app, dict):
        app_id = slack_app.get("app_id")
        slack_team_id = slack_app.get("team_id") or slack_app.get("enterprise_id")
        # Default policy: only redirect to Slack if we have required identifiers
        if app_id and slack_team_id:
            slack_url = (
                f"https://slack.com/app_redirect?app={app_id}&team={slack_team_id}"
            )
            log.info(f"Redirecting to Slack for team {public_id}")
            return {"target": "slack", "redirect_url": slack_url}
        else:
            log.error(f"Cannot resolve Slack join destination for team {public_id}: {slack_app}")
            raise HTTPException(status_code=500, detail="Internal error")
    else:
        webapp_url = os.getenv("WEBAPP_URL")
        web_url = f"{webapp_url}/join/form/{public_id}"
        log.info(f"Redirecting to web join for team {public_id} to {web_url}")
        return {"target": "web", "redirect_url": web_url}

