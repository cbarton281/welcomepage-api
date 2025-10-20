from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from utils.jwt_auth import get_current_user
from services.slack_publish_service import SlackPublishService
from schemas.slack_publish import (
    PublishWelcomepageRequest,
    PublishWelcomepageResponse,
    TestChannelRequest,
    TestChannelResponse
)
from utils.logger_factory import new_logger

router = APIRouter()


@router.post("/publish-welcomepage", response_model=PublishWelcomepageResponse)
async def publish_welcomepage_to_slack(
    request: PublishWelcomepageRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Publish a user's welcomepage to their team's designated Slack channel
    
    Requires USER or ADMIN role. Users can only publish their own welcomepage.
    """
    log = new_logger("publish_welcomepage_to_slack")
    
    # Validate user role
    if current_user.get('role') not in ['USER', 'ADMIN']:
        log.warning(f"Access denied for user {current_user.get('public_id')} with role {current_user.get('role')}")
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    # Users can only publish their own welcomepage (unless ADMIN)
    requesting_user_id = current_user.get('public_id')
    if current_user.get('role') != 'ADMIN' and request.user_public_id != requesting_user_id:
        log.warning(f"User {requesting_user_id} attempted to publish for user {request.user_public_id}")
        raise HTTPException(status_code=403, detail="You can only publish your own welcomepage")
    
    log.info(f"Publishing welcomepage for user {request.user_public_id} by {requesting_user_id}")
    
    # Check if payment is required (3+ published pages)
    from models.welcomepage_user import WelcomepageUser
    from models.team import Team
    
    user = db.query(WelcomepageUser).filter_by(public_id=request.user_public_id).first()
    if not user or not user.team:
        log.error(f"User {request.user_public_id} or team not found")
        raise HTTPException(status_code=404, detail="User or team not found")
    
    team = user.team
    
    # Get team admin's email for receipt
    admin_user = db.query(WelcomepageUser).filter(
        WelcomepageUser.team_id == team.id,
        WelcomepageUser.auth_role == "ADMIN"
    ).first()
    
    admin_email = admin_user.auth_email if admin_user else None
    log.info(f"Admin user found: {admin_user.public_id if admin_user else 'None'}")
    log.info(f"Admin email for receipt: {admin_email}")
    
    # Count published pages for this team (is_draft=False)
    published_count = db.query(WelcomepageUser).filter(
        WelcomepageUser.team_id == team.id,
        WelcomepageUser.is_draft == False
    ).count()
    
    log.info(f"Team {team.public_id} has {published_count} published pages")
    
    # If over 3-page free limit and has payment method, charge $7.99
    if published_count >= 3 and team.stripe_customer_id:
        log.info(f"Over free limit ({published_count} >= 3) and has payment method, charging $7.99")
        
        from services.stripe_service import StripeService
        
        try:
            charge_result = await StripeService.charge_for_welcomepage(
                team_public_id=team.public_id,
                team_stripe_customer_id=team.stripe_customer_id,
                user_public_id=user.public_id,
                user_name=user.name,
                admin_email=admin_email
            )
            
            if not charge_result.get("success"):
                log.error(f"Payment failed for user {user.public_id}: {charge_result}")
                raise HTTPException(
                    status_code=402,
                    detail={
                        "error": "Payment failed",
                        "message": "Payment failed. Please update your payment method in team settings."
                    }
                )
            
            log.info(f"Payment successful for user {user.public_id}, proceeding to publish")
            
        except Exception as e:
            log.error(f"Error charging for welcomepage: {str(e)}")
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "Payment failed",
                    "message": f"Payment failed: {str(e)}"
                }
            )
    elif published_count >= 3 and not team.stripe_customer_id:
        log.info(f"Over free limit ({published_count} >= 3) but no payment method, allowing free publish")
    
    # Call the service to publish to Slack
    result = SlackPublishService.publish_welcomepage(
        user_public_id=request.user_public_id,
        custom_message=request.custom_message,
        db=db
    )
    
    # Return appropriate response based on result
    if result["success"]:
        slack_response = result.get("slack_response")
        return PublishWelcomepageResponse(
            success=True,
            message=result["message"],
            slack_response=slack_response
        )
    else:
        # For client errors (user/team not found, no integration), return 400
        # For server errors, return 500
        if result.get("error") in ["User not found", "Team not found"]:
            status_code = 404
        elif result.get("error") in ["No Slack integration", "No publish channel", "Already published"]:
            status_code = 400
        else:
            status_code = 500
            
        raise HTTPException(
            status_code=status_code,
            detail={
                "error": result.get("error"),
                "message": result["message"],
                "slack_error": result.get("slack_error")
            }
        )


@router.post("/test-channel", response_model=TestChannelResponse)
async def test_slack_channel(
    request: TestChannelRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Test if the bot can post to a specific Slack channel
    
    Requires ADMIN role for team management.
    """
    log = new_logger("test_slack_channel")
    
    # Only ADMINs can test channels
    if current_user.get('role') != 'ADMIN':
        log.warning(f"Access denied for user {current_user.get('public_id')} with role {current_user.get('role')}")
        raise HTTPException(status_code=403, detail="Admin access required")
    
    # Get team from current user
    team_public_id = current_user.get('team_id')
    if not team_public_id:
        log.error(f"No team found for user {current_user.get('public_id')}")
        raise HTTPException(status_code=400, detail="User has no associated team")
    
    log.info(f"Testing Slack channel {request.channel_id} for team {team_public_id}")
    
    # Call the service to test the channel
    result = SlackPublishService.test_channel_connection(
        team_public_id=team_public_id,
        channel_id=request.channel_id
    )
    
    # Return appropriate response based on result
    if result["success"]:
        return TestChannelResponse(
            success=True,
            message=result["message"],
            slack_response=result.get("slack_response")
        )
    else:
        # For client errors (no integration, channel not found), return 400
        # For server errors, return 500
        if result.get("error") in ["No Slack integration"]:
            status_code = 400
        elif result.get("slack_error") in ["channel_not_found", "not_in_channel", "access_denied"]:
            status_code = 400
        else:
            status_code = 500
            
        raise HTTPException(
            status_code=status_code,
            detail={
                "error": result.get("error"),
                "message": result["message"],
                "slack_error": result.get("slack_error")
            }
        )
