"""CRUD operations for Mattermost bot models."""

from datetime import datetime
from datetime import timezone

from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import Session

from onyx.auth.api_key import build_displayable_api_key
from onyx.auth.api_key import generate_api_key
from onyx.auth.api_key import hash_api_key
from onyx.auth.schemas import UserRole
from onyx.configs.constants import MATTERMOST_SERVICE_API_KEY_NAME
from onyx.db.api_key import insert_api_key
from onyx.db.models import ApiKey
from onyx.db.models import MattermostBotConfig
from onyx.db.models import MattermostChannelConfig
from onyx.db.models import MattermostTeamConfig
from onyx.db.models import User
from onyx.db.utils import MattermostChannelView
from onyx.server.api_key.models import APIKeyArgs
from onyx.utils.logger import setup_logger

logger = setup_logger()


# === MattermostBotConfig ===


def get_mattermost_bot_config(db_session: Session) -> MattermostBotConfig | None:
    """Get the Mattermost bot config for this tenant (at most one)."""
    return db_session.scalar(select(MattermostBotConfig).limit(1))


def create_mattermost_bot_config(
    db_session: Session,
    server_url: str,
    bot_token: str,
    bot_user_id: str | None = None,
) -> MattermostBotConfig:
    """Create the Mattermost bot config. Raises ValueError if already exists.

    The check constraint on id='SINGLETON' ensures only one config per tenant.
    """
    existing = get_mattermost_bot_config(db_session)
    if existing:
        raise ValueError("Mattermost bot config already exists")

    config = MattermostBotConfig(
        server_url=server_url.rstrip("/"),
        bot_token=bot_token,
        bot_user_id=bot_user_id,
    )
    db_session.add(config)
    try:
        db_session.flush()
    except IntegrityError:
        db_session.rollback()
        raise ValueError("Mattermost bot config already exists")
    return config


def update_mattermost_bot_config(
    db_session: Session,
    config: MattermostBotConfig,
    server_url: str | None = None,
    bot_token: str | None = None,
    bot_user_id: str | None = None,
) -> MattermostBotConfig:
    """Update the Mattermost bot config."""
    if server_url is not None:
        config.server_url = server_url.rstrip("/")
    if bot_token is not None:
        config.bot_token = bot_token
    if bot_user_id is not None:
        config.bot_user_id = bot_user_id
    db_session.flush()
    return config


def delete_mattermost_bot_config(db_session: Session) -> bool:
    """Delete the Mattermost bot config. Returns True if deleted."""
    result = db_session.execute(delete(MattermostBotConfig))
    db_session.flush()
    return result.rowcount > 0  # type: ignore[attr-defined]


# === Mattermost Service API Key ===


def get_mattermost_service_api_key(db_session: Session) -> ApiKey | None:
    """Get the Mattermost service API key if it exists."""
    return db_session.scalar(
        select(ApiKey).where(ApiKey.name == MATTERMOST_SERVICE_API_KEY_NAME)
    )


def get_or_create_mattermost_service_api_key(
    db_session: Session,
    tenant_id: str,
) -> str:
    """Get existing Mattermost service API key or create one.

    The API key is used by the Mattermost bot to authenticate with the
    Onyx API pods when sending chat requests.

    Args:
        db_session: Database session for the tenant.
        tenant_id: The tenant ID (used for logging/context).

    Returns:
        The raw API key string (not hashed).

    Raises:
        RuntimeError: If API key creation fails.
    """
    existing = get_mattermost_service_api_key(db_session)
    if existing:
        logger.debug(
            f"Found existing Mattermost service API key for tenant {tenant_id} that isn't in cache, "
            "regenerating to update cache"
        )
        new_api_key = generate_api_key(tenant_id)
        existing.hashed_api_key = hash_api_key(new_api_key)
        existing.api_key_display = build_displayable_api_key(new_api_key)
        db_session.flush()
        return new_api_key

    logger.info(f"Creating Mattermost service API key for tenant {tenant_id}")
    api_key_args = APIKeyArgs(
        name=MATTERMOST_SERVICE_API_KEY_NAME,
        role=UserRole.LIMITED,
    )
    api_key_descriptor = insert_api_key(
        db_session=db_session,
        api_key_args=api_key_args,
        user_id=None,
    )

    if not api_key_descriptor.api_key:
        raise RuntimeError(
            f"Failed to create Mattermost service API key for tenant {tenant_id}"
        )

    return api_key_descriptor.api_key


def delete_mattermost_service_api_key(db_session: Session) -> bool:
    """Delete the Mattermost service API key for a tenant."""
    existing_key = get_mattermost_service_api_key(db_session)
    if not existing_key:
        return False

    api_key_user = db_session.scalar(
        select(User).where(User.id == existing_key.user_id)  # type: ignore[arg-type]
    )

    db_session.delete(existing_key)
    if api_key_user:
        db_session.delete(api_key_user)

    db_session.flush()
    logger.info("Deleted Mattermost service API key")
    return True


# === MattermostTeamConfig ===


def get_team_configs(
    db_session: Session,
    include_channels: bool = False,
) -> list[MattermostTeamConfig]:
    """Get all team configs for this tenant."""
    stmt = select(MattermostTeamConfig)
    if include_channels:
        stmt = stmt.options(joinedload(MattermostTeamConfig.channels))
    return list(db_session.scalars(stmt).unique().all())


def get_team_config_by_internal_id(
    db_session: Session,
    internal_id: int,
) -> MattermostTeamConfig | None:
    """Get a specific team config by its ID."""
    return db_session.scalar(
        select(MattermostTeamConfig).where(MattermostTeamConfig.id == internal_id)
    )


def get_team_config_by_mattermost_id(
    db_session: Session,
    team_id: str,
) -> MattermostTeamConfig | None:
    """Get a team config by Mattermost team ID."""
    return db_session.scalar(
        select(MattermostTeamConfig).where(MattermostTeamConfig.team_id == team_id)
    )


def get_team_config_by_registration_key(
    db_session: Session,
    registration_key: str,
) -> MattermostTeamConfig | None:
    """Get a team config by its registration key."""
    return db_session.scalar(
        select(MattermostTeamConfig).where(
            MattermostTeamConfig.registration_key == registration_key
        )
    )


def create_team_config(
    db_session: Session,
    registration_key: str,
) -> MattermostTeamConfig:
    """Create a new team config with a registration key (team_id=NULL)."""
    config = MattermostTeamConfig(registration_key=registration_key)
    db_session.add(config)
    db_session.flush()
    return config


def register_team(
    db_session: Session,
    config: MattermostTeamConfig,
    team_id: str,
    team_name: str,
) -> MattermostTeamConfig:
    """Complete registration by setting team_id and team_name."""
    config.team_id = team_id
    config.team_name = team_name
    config.registered_at = datetime.now(timezone.utc)
    db_session.flush()
    return config


def update_team_config(
    db_session: Session,
    config: MattermostTeamConfig,
    enabled: bool,
    default_persona_id: int | None = None,
) -> MattermostTeamConfig:
    """Update team config fields."""
    config.enabled = enabled
    config.default_persona_id = default_persona_id
    db_session.flush()
    return config


def delete_team_config(
    db_session: Session,
    internal_id: int,
) -> bool:
    """Delete team config (cascades to channel configs). Returns True if deleted."""
    result = db_session.execute(
        delete(MattermostTeamConfig).where(MattermostTeamConfig.id == internal_id)
    )
    db_session.flush()
    return result.rowcount > 0  # type: ignore[attr-defined]


# === MattermostChannelConfig ===


def get_channel_configs(
    db_session: Session,
    team_config_id: int,
) -> list[MattermostChannelConfig]:
    """Get all channel configs for a team."""
    return list(
        db_session.scalars(
            select(MattermostChannelConfig).where(
                MattermostChannelConfig.team_config_id == team_config_id
            )
        ).all()
    )


def get_channel_config_by_mattermost_ids(
    db_session: Session,
    team_id: str,
    channel_id: str,
) -> MattermostChannelConfig | None:
    """Get a specific channel config by team_id and channel_id."""
    return db_session.scalar(
        select(MattermostChannelConfig)
        .join(MattermostTeamConfig)
        .where(
            MattermostTeamConfig.team_id == team_id,
            MattermostChannelConfig.channel_id == channel_id,
        )
    )


def get_channel_config_by_internal_ids(
    db_session: Session,
    team_config_id: int,
    channel_config_id: int,
) -> MattermostChannelConfig | None:
    """Get a specific channel config by team_config_id and channel_config_id."""
    return db_session.scalar(
        select(MattermostChannelConfig).where(
            MattermostChannelConfig.team_config_id == team_config_id,
            MattermostChannelConfig.id == channel_config_id,
        )
    )


def update_mattermost_channel_config(
    db_session: Session,
    config: MattermostChannelConfig,
    channel_name: str,
    thread_only_mode: bool,
    require_bot_invocation: bool,
    enabled: bool,
    persona_override_id: int | None = None,
) -> MattermostChannelConfig:
    """Update channel config fields."""
    config.channel_name = channel_name
    config.require_bot_invocation = require_bot_invocation
    config.persona_override_id = persona_override_id
    config.enabled = enabled
    config.thread_only_mode = thread_only_mode
    db_session.flush()
    return config


def delete_mattermost_channel_config(
    db_session: Session,
    team_config_id: int,
    channel_config_id: int,
) -> bool:
    """Delete a channel config. Returns True if deleted."""
    result = db_session.execute(
        delete(MattermostChannelConfig).where(
            MattermostChannelConfig.team_config_id == team_config_id,
            MattermostChannelConfig.id == channel_config_id,
        )
    )
    db_session.flush()
    return result.rowcount > 0  # type: ignore[attr-defined]


def create_channel_config(
    db_session: Session,
    team_config_id: int,
    channel_view: MattermostChannelView,
) -> MattermostChannelConfig:
    """Create a new channel config with default settings (disabled by default)."""
    config = MattermostChannelConfig(
        team_config_id=team_config_id,
        channel_id=channel_view.channel_id,
        channel_name=channel_view.channel_name,
        channel_type=channel_view.channel_type,
    )
    db_session.add(config)
    db_session.flush()
    return config


def bulk_create_channel_configs(
    db_session: Session,
    team_config_id: int,
    channels: list[MattermostChannelView],
) -> list[MattermostChannelConfig]:
    """Create multiple channel configs at once. Skips existing channels."""
    existing_channel_ids = set(
        db_session.scalars(
            select(MattermostChannelConfig.channel_id).where(
                MattermostChannelConfig.team_config_id == team_config_id
            )
        ).all()
    )

    new_configs = []
    for channel_view in channels:
        if channel_view.channel_id not in existing_channel_ids:
            config = MattermostChannelConfig(
                team_config_id=team_config_id,
                channel_id=channel_view.channel_id,
                channel_name=channel_view.channel_name,
                channel_type=channel_view.channel_type,
            )
            db_session.add(config)
            new_configs.append(config)

    db_session.flush()
    return new_configs


def sync_channel_configs(
    db_session: Session,
    team_config_id: int,
    current_channels: list[MattermostChannelView],
) -> tuple[int, int, int]:
    """Sync channel configs with current Mattermost channels.

    - Creates configs for new channels (disabled by default)
    - Removes configs for deleted channels
    - Updates names and types for existing channels if changed

    Returns: (added_count, removed_count, updated_count)
    """
    current_channel_map = {
        channel_view.channel_id: channel_view for channel_view in current_channels
    }
    current_channel_ids = set(current_channel_map.keys())

    existing_configs = get_channel_configs(db_session, team_config_id)
    existing_channel_ids = {c.channel_id for c in existing_configs}

    to_add = current_channel_ids - existing_channel_ids
    to_remove = existing_channel_ids - current_channel_ids

    added_count = 0
    for channel_id in to_add:
        channel_view = current_channel_map[channel_id]
        create_channel_config(db_session, team_config_id, channel_view)
        added_count += 1

    removed_count = 0
    for config in existing_configs:
        if config.channel_id in to_remove:
            db_session.delete(config)
            removed_count += 1

    updated_count = 0
    for config in existing_configs:
        if config.channel_id in current_channel_ids:
            channel_view = current_channel_map[config.channel_id]
            changed = False
            if config.channel_name != channel_view.channel_name:
                config.channel_name = channel_view.channel_name
                changed = True
            if config.channel_type != channel_view.channel_type:
                config.channel_type = channel_view.channel_type
                changed = True
            if changed:
                updated_count += 1

    db_session.flush()
    return added_count, removed_count, updated_count
