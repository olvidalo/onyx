# Mattermost Bot Integration Status

## Overview

Scaffolded a self-hosted Mattermost bot integration for Onyx, following the existing Discord bot architecture.

## Files Created

### Core Bot Files (`/backend/onyx/onyxbot/mattermost/`)

| File | Purpose |
|------|---------|
| `__init__.py` | Package init |
| `constants.py` | Configuration constants (timeouts, emoji, limits) |
| `exceptions.py` | Custom exception classes |
| `api_client.py` | Async HTTP client for Onyx chat API |
| `cache.py` | Multi-tenant team→tenant→API key mapping cache |
| `handle_message.py` | WebSocket event parsing, response logic, message processing |
| `handle_commands.py` | `!register` and `!sync-channels` command handlers |
| `client.py` | Main `OnyxMattermostBot` class using mattermostdriver |

### Database Layer

| File | Changes |
|------|---------|
| `db/models.py` | Added `MattermostBotConfig`, `MattermostTeamConfig`, `MattermostChannelConfig` |
| `db/mattermost_bot.py` | CRUD operations for Mattermost bot models |
| `db/utils.py` | Added `MattermostChannelView` dataclass |

### Other Changes

| File | Change |
|------|--------|
| `server/query_and_chat/models.py` | Added `MATTERMOSTBOT` to `MessageOrigin` enum |
| `configs/constants.py` | Added `MATTERMOST_SERVICE_API_KEY_NAME` constant |
| `pyproject.toml` | Added `mattermostdriver==7.3.2` dependency |

## Architecture

```
WebSocket Events → MattermostMessage.from_websocket_event()
       ↓
should_respond() → Check team/channel config
       ↓
process_chat_message() → Build context, call Onyx API
       ↓
send_response() → Post via driver.posts.create_post()
```

## Key Technical Details

- Uses [mattermostdriver](https://vaelor.github.io/python-mattermost-driver/) Python SDK
- WebSocket events have nested JSON (data.post and data.mentions are JSON strings)
- `root_id` is empty string for non-threaded posts, parent post ID for replies
- Multi-tenant support via cache mapping team_id → tenant_id → api_key

## Still Needed for Production

1. **Database migration** - Run Alembic to create the new tables
2. **Admin UI** - Web interface to configure bot credentials and teams
3. **Docker service** - Add mattermost_bot service to docker-compose
4. **Registration key generation** - API endpoint to create `mattermost_<tenant_id>.<token>` keys
5. **Channel sync** - Implement fetching channels from Mattermost API

## Usage (once complete)

1. Admin configures Mattermost server URL and bot token in Onyx
2. Admin generates registration key for a team
3. In Mattermost, admin runs `!register <key>` to link team to Onyx
4. Bot responds to @mentions in enabled channels
