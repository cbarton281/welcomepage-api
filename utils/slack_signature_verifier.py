import os
import hashlib
import hmac
import time
from typing import Optional

from utils.logger_factory import new_logger


class SlackSignatureVerifier:
    """Utility for verifying Slack request signatures"""
    
    def __init__(self):
        self.signing_secret = os.getenv("SLACK_SIGNING_SECRET")
        if not self.signing_secret:
            raise ValueError("SLACK_SIGNING_SECRET environment variable must be set")
    
    def verify_signature(self, body: bytes, timestamp: str, signature: str) -> bool:
        """
        Verify that a request came from Slack
        
        Args:
            body: Raw request body bytes
            timestamp: X-Slack-Request-Timestamp header value
            signature: X-Slack-Signature header value
            
        Returns:
            True if signature is valid, False otherwise
        """
        log = new_logger("slack_signature_verifier")
        
        try:
            # Check timestamp to prevent replay attacks (within 5 minutes)
            if not self._is_timestamp_valid(timestamp):
                log.warning("Request timestamp is too old or invalid")
                return False
            
            # Create the signature base string
            sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
            
            # Create the expected signature
            expected_signature = 'v0=' + hmac.new(
                self.signing_secret.encode(),
                sig_basestring.encode(),
                hashlib.sha256
            ).hexdigest()
            
            # Compare signatures using secure comparison
            is_valid = hmac.compare_digest(expected_signature, signature)
            
            if not is_valid:
                log.warning(f"Signature verification failed. Expected: {expected_signature}, Got: {signature}")
            else:
                log.info("Slack signature verification successful")
                
            return is_valid
            
        except Exception as e:
            log.error(f"Error verifying Slack signature: {str(e)}")
            return False
    
    def _is_timestamp_valid(self, timestamp: str) -> bool:
        """
        Check if timestamp is within acceptable range (5 minutes)
        to prevent replay attacks
        """
        try:
            request_timestamp = int(timestamp)
            current_timestamp = int(time.time())
            
            # Allow requests within 5 minutes (300 seconds)
            time_diff = abs(current_timestamp - request_timestamp)
            return time_diff <= 300
            
        except (ValueError, TypeError):
            return False
