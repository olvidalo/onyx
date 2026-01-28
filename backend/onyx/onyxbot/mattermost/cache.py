"""Multi-tenant cache for Mattermost bot team-tenant mappings and API keys."""

import asyncio

from onyx.db.mattermost_bot import get_mattermost_bot_config
from onyx.db.mattermost_bot import get_or_create_mattermost_service_api_key
from onyx.db.mattermost_bot import get_team_configs
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.engine.tenant_utils import get_all_tenant_ids
from onyx.onyxbot.mattermost.exceptions import CacheError
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()


class MattermostCacheManager:
    """Caches team->tenant mappings and tenant->API key/server URL mappings.

    Refreshed on startup, periodically (every 60s), and when teams register.
    """

    def __init__(self) -> None:
        self._team_tenants: dict[str, str] = {}  # team_id -> tenant_id
        self._api_keys: dict[str, str] = {}  # tenant_id -> api_key
        self._server_urls: dict[str, str] = {}  # tenant_id -> server_url
        self._bot_tokens: dict[str, str] = {}  # tenant_id -> bot_token
        self._lock = asyncio.Lock()
        self._initialized = False

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    async def refresh_all(self) -> None:
        """Full cache refresh from all tenants."""
        async with self._lock:
            logger.info("Starting Mattermost cache refresh")

            new_team_tenants: dict[str, str] = {}
            new_api_keys: dict[str, str] = {}
            new_server_urls: dict[str, str] = {}
            new_bot_tokens: dict[str, str] = {}

            try:
                gated = fetch_ee_implementation_or_noop(
                    "onyx.server.tenants.product_gating",
                    "get_gated_tenants",
                    set(),
                )()

                tenant_ids = await asyncio.to_thread(get_all_tenant_ids)
                for tenant_id in tenant_ids:
                    if tenant_id in gated:
                        continue

                    context_token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
                    try:
                        team_ids, api_key, server_url, bot_token = (
                            await self._load_tenant_data(tenant_id)
                        )
                        if not team_ids:
                            logger.debug(f"No teams found for tenant {tenant_id}")
                            continue

                        if not api_key:
                            logger.warning(
                                "Mattermost service API key missing for tenant that has registered teams. "
                                f"{tenant_id} will not be handled in this refresh cycle."
                            )
                            continue

                        for team_id in team_ids:
                            new_team_tenants[team_id] = tenant_id

                        new_api_keys[tenant_id] = api_key
                        if server_url:
                            new_server_urls[tenant_id] = server_url
                        if bot_token:
                            new_bot_tokens[tenant_id] = bot_token
                    except Exception as e:
                        logger.warning(f"Failed to refresh tenant {tenant_id}: {e}")
                    finally:
                        CURRENT_TENANT_ID_CONTEXTVAR.reset(context_token)

                self._team_tenants = new_team_tenants
                self._api_keys = new_api_keys
                self._server_urls = new_server_urls
                self._bot_tokens = new_bot_tokens
                self._initialized = True

                logger.info(
                    f"Cache refresh complete: {len(new_team_tenants)} teams, "
                    f"{len(new_api_keys)} tenants"
                )

            except Exception as e:
                logger.error(f"Cache refresh failed: {e}")
                raise CacheError(f"Failed to refresh cache: {e}") from e

    async def refresh_team(self, team_id: str, tenant_id: str) -> None:
        """Add a single team to cache after registration."""
        async with self._lock:
            logger.info(f"Refreshing cache for team {team_id} (tenant: {tenant_id})")

            team_ids, api_key, server_url, bot_token = await self._load_tenant_data(
                tenant_id
            )

            if team_id in team_ids:
                self._team_tenants[team_id] = tenant_id
                if api_key:
                    self._api_keys[tenant_id] = api_key
                if server_url:
                    self._server_urls[tenant_id] = server_url
                if bot_token:
                    self._bot_tokens[tenant_id] = bot_token
                logger.info(f"Cache updated for team {team_id}")
            else:
                logger.warning(f"Team {team_id} not found or disabled")

    async def _load_tenant_data(
        self, tenant_id: str
    ) -> tuple[list[str], str | None, str | None, str | None]:
        """Load team IDs, API key, server URL, and bot token.

        Returns:
            (active_team_ids, api_key, server_url, bot_token)
        """
        cached_key = self._api_keys.get(tenant_id)

        def _sync() -> tuple[list[str], str | None, str | None, str | None]:
            with get_session_with_tenant(tenant_id=tenant_id) as db:
                # Get bot config for server URL and token
                bot_config = get_mattermost_bot_config(db)
                server_url = bot_config.server_url if bot_config else None
                bot_token = bot_config.bot_token if bot_config else None

                # Get team configs
                configs = get_team_configs(db)
                team_ids = [
                    config.team_id
                    for config in configs
                    if config.enabled and config.team_id is not None
                ]

                if not team_ids:
                    return [], None, server_url, bot_token

                if not cached_key:
                    new_key = get_or_create_mattermost_service_api_key(db, tenant_id)
                    db.commit()
                    return team_ids, new_key, server_url, bot_token

                return team_ids, cached_key, server_url, bot_token

        return await asyncio.to_thread(_sync)

    def get_tenant(self, team_id: str) -> str | None:
        """Get tenant ID for a team."""
        return self._team_tenants.get(team_id)

    def get_api_key(self, tenant_id: str) -> str | None:
        """Get API key for a tenant."""
        return self._api_keys.get(tenant_id)

    def get_server_url(self, tenant_id: str) -> str | None:
        """Get Mattermost server URL for a tenant."""
        return self._server_urls.get(tenant_id)

    def get_bot_token(self, tenant_id: str) -> str | None:
        """Get bot token for a tenant."""
        return self._bot_tokens.get(tenant_id)

    def remove_team(self, team_id: str) -> None:
        """Remove a team from cache."""
        self._team_tenants.pop(team_id, None)

    def get_all_team_ids(self) -> list[str]:
        """Get all cached team IDs."""
        return list(self._team_tenants.keys())

    def get_all_tenants_with_bots(self) -> list[tuple[str, str, str]]:
        """Get all tenants with configured bots.

        Returns:
            List of (tenant_id, server_url, bot_token) tuples
        """
        result = []
        for tenant_id in self._bot_tokens:
            server_url = self._server_urls.get(tenant_id)
            bot_token = self._bot_tokens.get(tenant_id)
            if server_url and bot_token:
                result.append((tenant_id, server_url, bot_token))
        return result

    def clear(self) -> None:
        """Clear all caches."""
        self._team_tenants.clear()
        self._api_keys.clear()
        self._server_urls.clear()
        self._bot_tokens.clear()
        self._initialized = False
