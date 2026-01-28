"""Mattermost bot command handlers for registration and channel sync.

Commands are triggered via bot mentions with specific keywords:
- !register <registration_key> - Register this team with Onyx
- !sync-channels - Sync channel list with Onyx
"""

import asyncio
from datetime import datetime
from datetime import timezone

from onyx.db.mattermost_bot import bulk_create_channel_configs
from onyx.db.mattermost_bot import get_team_config_by_mattermost_id
from onyx.db.mattermost_bot import get_team_config_by_registration_key
from onyx.db.mattermost_bot import sync_channel_configs
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.utils import MattermostChannelView
from onyx.onyxbot.mattermost.cache import MattermostCacheManager
from onyx.onyxbot.mattermost.constants import REGISTER_COMMAND
from onyx.onyxbot.mattermost.constants import SYNC_CHANNELS_COMMAND
from onyx.onyxbot.mattermost.exceptions import RegistrationError
from onyx.onyxbot.mattermost.exceptions import SyncChannelsError
from onyx.onyxbot.mattermost.handle_message import MattermostDriverWrapper
from onyx.onyxbot.mattermost.handle_message import MattermostMessage
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()


def parse_mattermost_registration_key(key: str) -> str | None:
    """Parse a Mattermost registration key to extract tenant_id.

    Format: mattermost_<tenant_id>.<random_token>

    Returns tenant_id or None if invalid format.
    """
    if not key.startswith("mattermost_"):
        return None

    # Remove prefix
    rest = key[len("mattermost_"):]

    # Split on first dot
    if "." not in rest:
        return None

    tenant_id = rest.split(".", 1)[0]
    return tenant_id if tenant_id else None


async def handle_command(
    message: MattermostMessage,
    cache: MattermostCacheManager,
    mm_driver: MattermostDriverWrapper,
    bot_user_id: str,
) -> bool:
    """Handle bot commands. Returns True if a command was processed.

    Commands must be directed at the bot (mentioned) and start with !.
    """
    content = message.message.strip()

    # Check if this is a command (starts with !)
    if not content.startswith("!"):
        return False

    # Check for !register command
    if content.startswith(f"!{REGISTER_COMMAND}"):
        await handle_registration_command(message, cache, mm_driver)
        return True

    # Check for !sync-channels command
    if content.startswith(f"!{SYNC_CHANNELS_COMMAND}"):
        tenant_id = cache.get_tenant(message.team_id)
        await handle_sync_channels_command(message, tenant_id, mm_driver)
        return True

    return False


async def handle_registration_command(
    message: MattermostMessage,
    cache: MattermostCacheManager,
    mm_driver: MattermostDriverWrapper,
) -> None:
    """Handle !register <key> command."""
    content = message.message.strip()
    team_id = message.team_id

    logger.info(f"Registration command received for team {team_id}")

    try:
        # Parse the registration key
        parts = content.split(maxsplit=1)
        if len(parts) < 2:
            raise RegistrationError(
                "Invalid registration key format. Usage: `!register <key>`"
            )

        registration_key = parts[1].strip()

        # Check if already registered
        existing_tenant = cache.get_tenant(team_id)
        if existing_tenant is not None:
            raise RegistrationError(
                "This team is already registered with Onyx.\n\n"
                "OnyxBot can only connect one Mattermost team to one Onyx workspace."
            )

        # Parse tenant_id from key
        tenant_id = parse_mattermost_registration_key(registration_key)
        if not tenant_id:
            raise RegistrationError(
                "Invalid registration key format. Please check the key and try again."
            )

        # Perform registration
        await _register_team(message, registration_key, tenant_id, cache, mm_driver)

        logger.info(f"Registration successful for team {team_id}")

        # Send success message
        await mm_driver.create_post(
            channel_id=message.channel_id,
            message=(
                ":white_check_mark: **Successfully registered!**\n\n"
                "This team is now connected to Onyx. "
                "I'll respond to messages based on your team and channel settings in Onyx."
            ),
            root_id=message.post_id if message.is_thread else None,
        )

    except RegistrationError as e:
        logger.debug(f"Registration failed for team {team_id}: {e}")
        await mm_driver.create_post(
            channel_id=message.channel_id,
            message=f":x: **Registration failed.**\n\n{e}",
            root_id=message.post_id if message.is_thread else None,
        )

    except Exception:
        logger.exception(f"Registration failed unexpectedly for team {team_id}")
        await mm_driver.create_post(
            channel_id=message.channel_id,
            message=(
                ":x: **Registration failed.**\n\n"
                "An unexpected error occurred. Please try again later."
            ),
            root_id=message.post_id if message.is_thread else None,
        )


async def _register_team(
    message: MattermostMessage,
    registration_key: str,
    tenant_id: str,
    cache: MattermostCacheManager,
    mm_driver: MattermostDriverWrapper,
) -> None:
    """Perform team registration."""
    team_id = message.team_id

    context_token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    try:
        # Get channels from the team (we'd need to fetch these from Mattermost)
        # For now, we'll create empty channel configs that can be synced later
        channels: list[MattermostChannelView] = []

        def _sync_register() -> int:
            with get_session_with_tenant(tenant_id=tenant_id) as db:
                # Find the team config by registration key
                config = get_team_config_by_registration_key(db, registration_key)
                if not config:
                    raise RegistrationError(
                        "Registration key not found.\n\n"
                        "The key may have expired or been deleted. "
                        "Please generate a new one from the Onyx admin panel."
                    )

                # Check if already used
                if config.team_id is not None:
                    raise RegistrationError(
                        "This registration key has already been used.\n\n"
                        "Each key can only be used once. "
                        "Please generate a new key from the Onyx admin panel."
                    )

                # Update the team config
                config.team_id = team_id
                config.team_name = f"Team {team_id[:8]}"  # We don't have team name yet
                config.registered_at = datetime.now(timezone.utc)

                # Create channel configs if we have any
                if channels:
                    bulk_create_channel_configs(db, config.id, channels)

                db.commit()
                return config.id

        await asyncio.to_thread(_sync_register)

        # Refresh cache for this team
        await cache.refresh_team(team_id, tenant_id)

        logger.info(f"Team '{team_id}' registered successfully")

    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(context_token)


async def handle_sync_channels_command(
    message: MattermostMessage,
    tenant_id: str | None,
    mm_driver: MattermostDriverWrapper,
) -> None:
    """Handle !sync-channels command."""
    team_id = message.team_id

    logger.info(f"Sync-channels command received for team {team_id}")

    try:
        if not tenant_id:
            raise SyncChannelsError(
                "This team is not registered. Please register it first using "
                "`!register <key>`"
            )

        # Get team config ID
        def _get_team_config_id() -> int | None:
            with get_session_with_tenant(tenant_id=tenant_id) as db:
                config = get_team_config_by_mattermost_id(db, team_id)
                return config.id if config else None

        team_config_id = await asyncio.to_thread(_get_team_config_id)

        if not team_config_id:
            raise SyncChannelsError(
                "Team config not found. This shouldn't happen. "
                "Please contact your administrator."
            )

        # For now, inform user that sync needs to be done via admin panel
        # Full implementation would fetch channels from Mattermost API
        await mm_driver.create_post(
            channel_id=message.channel_id,
            message=(
                ":information_source: **Channel Sync**\n\n"
                "To sync channels, please use the Onyx admin panel.\n\n"
                "Channel configuration allows you to:\n"
                "- Enable/disable specific channels\n"
                "- Set channel-specific personas\n"
                "- Configure mention requirements"
            ),
            root_id=message.post_id if message.is_thread else None,
        )

        logger.info(f"Sync-channels info provided for team {team_id}")

    except SyncChannelsError as e:
        logger.debug(f"Sync-channels failed for team {team_id}: {e}")
        await mm_driver.create_post(
            channel_id=message.channel_id,
            message=f":x: **Channel sync failed.**\n\n{e}",
            root_id=message.post_id if message.is_thread else None,
        )

    except Exception:
        logger.exception(f"Sync-channels failed unexpectedly for team {team_id}")
        await mm_driver.create_post(
            channel_id=message.channel_id,
            message=(
                ":x: **Channel sync failed.**\n\n"
                "An unexpected error occurred. Please try again later."
            ),
            root_id=message.post_id if message.is_thread else None,
        )


async def sync_team_channels(
    team_config_id: int,
    tenant_id: str,
    channels: list[MattermostChannelView],
) -> tuple[int, int, int]:
    """Sync channel configs with current Mattermost channels.

    Args:
        team_config_id: Internal ID of the team config
        tenant_id: Tenant ID for database access
        channels: List of current channels from Mattermost

    Returns:
        (added_count, removed_count, updated_count)
    """
    context_token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    try:

        def _sync() -> tuple[int, int, int]:
            with get_session_with_tenant(tenant_id=tenant_id) as db:
                added, removed, updated = sync_channel_configs(
                    db, team_config_id, channels
                )
                db.commit()
                return added, removed, updated

        return await asyncio.to_thread(_sync)

    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(context_token)
