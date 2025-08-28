from sqlalchemy.orm import Session
from models.slack_state_store import SlackStateStore
from datetime import datetime
from utils.logger_factory import new_logger
from typing import Optional

class SlackStateManager:
    """Manages OAuth state for Slack installations"""
    
    def __init__(self, db: Session, expiration_seconds: int = 300):
        self.db = db
        self.expiration_seconds = expiration_seconds
    
    def issue_state(self, team_public_id: str, initiator_public_user_id: Optional[str] = None) -> str:
        """Generate and store a new OAuth state, including the initiating user's public_id"""
        log = new_logger("issue_state")
        try:
            state_record = SlackStateStore(
                team_public_id=team_public_id,
                initiator_public_user_id=initiator_public_user_id,
                expiration_seconds=self.expiration_seconds,
            )
            self.db.add(state_record)
            self.db.commit()
            self.db.refresh(state_record)
            
            log.info(
                f"Issued OAuth state={state_record.state} for team_public_id={team_public_id} "
                f"initiator_public_user_id={initiator_public_user_id}"
            )
            return state_record.state
            
        except Exception as e:
            log.error(f"Failed to issue OAuth state: {str(e)}")
            self.db.rollback()
            raise
    
    def consume_state(self, state: str) -> bool:
        """Validate and consume an OAuth state"""
        log = new_logger("consume_state")
        try:
            state_record = self.db.query(SlackStateStore).filter_by(state=state).first()
            
            if not state_record:
                log.warning(f"OAuth state not found: {state}")
                return False
            
            if not state_record.is_valid():
                log.warning(f"OAuth state invalid (expired or consumed): {state}")
                return False
            
            # Mark as consumed
            state_record.consume()
            self.db.commit()
            
            log.info(f"Successfully consumed OAuth state: {state}")
            return True
            
        except Exception as e:
            log.error(f"Failed to consume OAuth state {state}: {str(e)}")
            self.db.rollback()
            return False
    
    def get_team_public_id_from_state(self, state: str) -> str:
        """Get the team_public_id associated with a state"""
        log = new_logger("get_team_public_id_from_state")
        try:
            state_record = self.db.query(SlackStateStore).filter_by(state=state).first()
            
            if not state_record:
                log.warning(f"OAuth state not found: {state}")
                return None
            
            if not state_record.is_valid():
                log.warning(f"OAuth state invalid (expired or consumed): {state}")
                return None
            
            return state_record.team_public_id
            
        except Exception as e:
            log.error(f"Failed to get team_public_id for state {state}: {str(e)}")
            return None

    def get_initiator_public_user_id_from_state(self, state: str) -> Optional[str]:
        """Get the initiator_public_user_id associated with a state"""
        log = new_logger("get_initiator_public_user_id_from_state")
        try:
            state_record = self.db.query(SlackStateStore).filter_by(state=state).first()
            if not state_record:
                log.warning(f"OAuth state not found: {state}")
                return None
            if not state_record.is_valid():
                log.warning(f"OAuth state invalid (expired or consumed): {state}")
                return None
            log.info(
                f"Resolved initiator_public_user_id={state_record.initiator_public_user_id} "
                f"for state {state}"
            )
            return state_record.initiator_public_user_id
        except Exception as e:
            log.error(f"Failed to get initiator_public_user_id for state {state}: {str(e)}")
            return None
    
    def cleanup_expired_states(self):
        """Remove expired state records from database"""
        log = new_logger("cleanup_expired_states")
        try:
            current_time = datetime.utcnow()
            expired_count = self.db.query(SlackStateStore).filter(
                SlackStateStore.expires_at < current_time
            ).delete()
            
            self.db.commit()
            
            if expired_count > 0:
                log.info(f"Cleaned up {expired_count} expired OAuth states")
                
        except Exception as e:
            log.error(f"Failed to cleanup expired states: {str(e)}")
            self.db.rollback()
