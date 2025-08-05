# Slack Installation Integration

This document describes the Slack installation flow implementation for the Welcomepage FastAPI application.

## Overview

The Slack installation allows teams to integrate their Welcomepage with Slack workspaces. All Slack installation data is stored in the `team.slack_settings` JSON field, and the OAuth flow is managed through secure state management.

## Architecture

### Components

1. **Models**
   - `SlackStateStore`: Manages OAuth state tokens with expiration
   - `Team`: Extended with `slack_settings` JSON field for installation data

2. **Services**
   - `SlackInstallationService`: Core service handling OAuth flow and installation management
   - `SlackStateManager`: Utility for OAuth state generation and validation

3. **API Endpoints**
   - `GET /api/slack/oauth/start`: Initiate OAuth flow
   - `GET /api/slack/oauth/callback`: Handle OAuth callback from Slack
   - `GET /api/slack/installation/{team_public_id}`: Get installation status
   - `DELETE /api/slack/installation/{team_public_id}`: Uninstall Slack integration
   - `POST /api/slack/cleanup-expired-states`: Cleanup expired OAuth states

### Database Schema

#### SlackStateStore Table
```sql
CREATE TABLE slack_state_store (
    id SERIAL PRIMARY KEY,
    state VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    consumed BOOLEAN NOT NULL DEFAULT FALSE
);
```

#### Team.slack_settings JSON Structure
```json
{
    "app_id": "A1234567890",
    "enterprise_id": "E1234567890",
    "enterprise_name": "Enterprise Name",
    "enterprise_url": "https://enterprise.slack.com/",
    "team_id": "T1234567890",
    "team_name": "Team Name",
    "bot_token": "xoxb-...",
    "bot_id": "B1234567890",
    "bot_user_id": "U1234567890",
    "bot_scopes": "channels:join,channels:manage,channels:read,chat:write,commands,im:write,users.profile:read,users:read",
    "user_id": "U1234567890",
    "user_token": "xoxp-...",
    "user_scopes": "users.profile:write,users:read",
    "incoming_webhook_url": "https://hooks.slack.com/...",
    "incoming_webhook_channel": "#general",
    "incoming_webhook_channel_id": "C1234567890",
    "incoming_webhook_configuration_url": "https://...",
    "is_enterprise_install": false,
    "token_type": "bot",
    "installed_at": "2025-08-04T18:15:00.000000",
    "installer_user_id": "U1234567890"
}
```

## Installation Flow

### 1. OAuth Start
```http
GET /api/slack/oauth/start
Authorization: Bearer <jwt_token>
```

**Requirements:**
- User must be authenticated
- User must have ADMIN role

**Response:**
```json
{
    "authorize_url": "https://slack.com/oauth/v2/authorize?client_id=...&scope=...&state=...",
    "state": "uuid-state-token"
}
```

### 2. OAuth Callback
```http
GET /api/slack/oauth/callback?code=...&state=...&team_public_id=...
```

**Parameters:**
- `code`: Authorization code from Slack
- `state`: OAuth state token for validation
- `team_public_id`: Target team for installation
- `error`: Optional error parameter if user cancels

**Flow:**
1. Validate OAuth state token
2. Exchange authorization code for access tokens
3. Extract installation data from OAuth response
4. Get bot information using bot token
5. Save installation data to team's `slack_settings`
6. Redirect to success/error page

### 3. Installation Status
```http
GET /api/slack/installation/{team_public_id}
Authorization: Bearer <jwt_token>
```

**Response (Installed):**
```json
{
    "installed": true,
    "team_id": "T1234567890",
    "team_name": "Team Name",
    "enterprise_id": "E1234567890",
    "enterprise_name": "Enterprise Name",
    "is_enterprise_install": false,
    "installed_at": "2025-08-04T18:15:00.000000",
    "bot_scopes": "channels:join,channels:manage,...",
    "user_scopes": "users.profile:write,users:read"
}
```

**Response (Not Installed):**
```json
{
    "installed": false,
    "message": "Slack not installed for this team"
}
```

### 4. Uninstall
```http
DELETE /api/slack/installation/{team_public_id}
Authorization: Bearer <jwt_token>
```

**Requirements:**
- User must be authenticated
- User must have ADMIN role
- User must belong to the target team

**Process:**
1. Revoke bot and user tokens via Slack API
2. Clear `team.slack_settings` field
3. Return success response

## Enterprise Support

The implementation fully supports Slack Enterprise Grid installations:

- **Enterprise Detection**: `is_enterprise_install` flag from OAuth response
- **Enterprise Data**: Stores `enterprise_id`, `enterprise_name`, and `enterprise_url`
- **Team Context**: Maintains both enterprise and workspace team information
- **Token Management**: Handles enterprise-level token scoping

## Security Features

### OAuth State Management
- **Unique States**: UUID-based state tokens
- **Expiration**: 5-minute expiration window (configurable)
- **Single Use**: States are consumed after validation
- **Cleanup**: Periodic cleanup of expired states

### Access Control
- **Admin Only**: Installation/uninstallation requires ADMIN role
- **Team Isolation**: Users can only manage their own team's installations
- **Token Security**: Sensitive tokens are not exposed in API responses

### Error Handling
- **Token Revocation**: Failed installations trigger automatic token cleanup
- **Graceful Failures**: Proper error responses and redirects
- **Logging**: Comprehensive logging for debugging and monitoring

## Environment Variables

Required environment variables:

```bash
SLACK_CLIENT_ID=your_slack_client_id
SLACK_CLIENT_SECRET=your_slack_client_secret
```

## Slack App Configuration

### OAuth & Permissions
- **Redirect URLs**: 
  - `https://your-api-domain.com/api/slack/oauth/callback`
- **Bot Token Scopes**:
  - `channels:join`
  - `channels:manage`
  - `channels:read`
  - `chat:write`
  - `commands`
  - `im:write`
  - `users.profile:read`
  - `users:read`
- **User Token Scopes**:
  - `users.profile:write`
  - `users:read`

### App Settings
- **App Name**: Welcomepage
- **Short Description**: Team member introduction and onboarding
- **App Icon**: Welcomepage logo
- **Background Color**: Brand color

## Usage Examples

### Frontend Integration
```typescript
// Start OAuth flow
const response = await fetch('/api/slack/oauth/start', {
    headers: { 'Authorization': `Bearer ${jwt}` }
});
const { authorize_url } = await response.json();
window.location.href = authorize_url;

// Check installation status
const status = await fetch(`/api/slack/installation/${teamId}`, {
    headers: { 'Authorization': `Bearer ${jwt}` }
});
const installation = await status.json();

// Uninstall
await fetch(`/api/slack/installation/${teamId}`, {
    method: 'DELETE',
    headers: { 'Authorization': `Bearer ${jwt}` }
});
```

### Backend Usage
```python
from services.slack_installation_service import SlackInstallationService

# Get installation for team
service = SlackInstallationService(db)
installation = service.get_installation_for_team(team_public_id)

if installation:
    # Use bot token for Slack API calls
    client = WebClient(token=installation.bot_token)
    response = client.chat_postMessage(
        channel="#general",
        text="Hello from Welcomepage!"
    )
```

## Monitoring and Maintenance

### Periodic Tasks
- **State Cleanup**: Run `POST /api/slack/cleanup-expired-states` periodically
- **Token Validation**: Monitor for revoked tokens
- **Installation Health**: Check installation status for active teams

### Logging
All Slack operations are logged with appropriate levels:
- **INFO**: Successful operations
- **WARNING**: Non-critical issues (e.g., token revocation failures)
- **ERROR**: Critical failures requiring attention

### Error Scenarios
- **Invalid State**: Expired or tampered OAuth states
- **Token Revocation**: Slack tokens revoked by workspace admin
- **API Limits**: Slack API rate limiting
- **Network Issues**: Connectivity problems with Slack API
