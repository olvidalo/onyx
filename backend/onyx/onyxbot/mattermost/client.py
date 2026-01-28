"""Mattermost bot client with integrated message handling.

Uses the mattermostdriver package to connect to self-hosted Mattermost instances.
Documentation: https://vaelor.github.io/python-mattermost-driver/
"""

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from mattermostdriver import Driver

from onyx.onyxbot.mattermost.api_client import OnyxAPIClient
from onyx.onyxbot.mattermost.cache import MattermostCacheManager
from onyx.onyxbot.mattermost.constants import (
    CACHE_REFRESH_INTERVAL,
    MAX_RECONNECT_ATTEMPTS,
    RECONNECT_DELAY,
)
from onyx.onyxbot.mattermost.handle_message import (
    MattermostDriverWrapper,
    MattermostMessage,
    process_chat_message,
    should_respond,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


class MattermostDriverImpl(MattermostDriverWrapper):
    """Implementation of MattermostDriverWrapper using mattermostdriver.

    Wraps the synchronous mattermostdriver API to provide async methods
    using a thread pool executor.
    """

    def __init__(self, driver: Driver, executor: ThreadPoolExecutor) -> None:
        self._driver = driver
        self._executor = executor

    async def _run_sync(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Run a synchronous function in the thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor, lambda: func(*args, **kwargs)
        )

    async def add_reaction(
        self, post_id: str, emoji_name: str, user_id: str
    ) -> None:
        """Add a reaction to a post.

        Uses: driver.reactions.create_reaction(options)
        """
        await self._run_sync(
            self._driver.reactions.create_reaction,
            options={
                "user_id": user_id,
                "post_id": post_id,
                "emoji_name": emoji_name,
            },
        )

    async def remove_reaction(
        self, post_id: str, emoji_name: str, user_id: str
    ) -> None:
        """Remove a reaction from a post.

        Uses: driver.reactions.delete_reaction(user_id, post_id, emoji_name)
        """
        await self._run_sync(
            self._driver.reactions.delete_reaction,
            user_id,
            post_id,
            emoji_name,
        )

    async def create_post(
        self,
        channel_id: str,
        message: str,
        root_id: str | None = None,
    ) -> dict:
        """Create a new post in a channel.

        Uses: driver.posts.create_post(options)
        """
        options: dict[str, Any] = {
            "channel_id": channel_id,
            "message": message,
        }
        if root_id:
            options["root_id"] = root_id

        return await self._run_sync(
            self._driver.posts.create_post,
            options=options,
        )

    async def get_thread(self, post_id: str) -> dict:
        """Get all posts in a thread.

        Uses: driver.posts.get_thread(post_id)
        Returns: {"order": [post_ids...], "posts": {post_id: post_data...}}
        """
        return await self._run_sync(
            self._driver.posts.get_thread,
            post_id,
        )

    async def get_user(self, user_id: str) -> dict:
        """Get user info by ID.

        Uses: driver.users.get_user(user_id)
        """
        return await self._run_sync(
            self._driver.users.get_user,
            user_id,
        )

    async def get_channels_for_team(self, user_id: str, team_id: str) -> list[dict]:
        """Get channels for a user in a team.

        Uses: driver.channels.get_channels_for_user(user_id, team_id)
        """
        return await self._run_sync(
            self._driver.channels.get_channels_for_user,
            user_id,
            team_id,
        )


class OnyxMattermostBot:
    """Mattermost bot client for Onyx.

    Connects to multiple Mattermost servers (one per tenant) using WebSocket
    for real-time message handling.

    Architecture:
    - One Driver instance per tenant/server
    - Shared cache for team->tenant mappings
    - Shared API client for Onyx backend calls
    - WebSocket event handlers process messages asynchronously
    """

    def __init__(self) -> None:
        self._drivers: dict[str, Driver] = {}  # tenant_id -> Driver
        self._driver_wrappers: dict[str, MattermostDriverImpl] = {}
        self._bot_user_ids: dict[str, str] = {}  # tenant_id -> bot_user_id
        self._executor = ThreadPoolExecutor(max_workers=10)

        self.cache = MattermostCacheManager()
        self.api_client = OnyxAPIClient()

        self._running = False
        self._cache_refresh_task: asyncio.Task | None = None
        self._websocket_tasks: dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        """Start the bot and connect to all configured servers."""
        logger.info("Starting Onyx Mattermost Bot...")

        # Initialize API client
        await self.api_client.initialize()

        # Load cache
        await self.cache.refresh_all()

        self._running = True

        # Start cache refresh task
        self._cache_refresh_task = asyncio.create_task(self._periodic_cache_refresh())

        # Connect to all servers
        await self._connect_all_servers()

        logger.info("Mattermost bot started successfully")

    async def stop(self) -> None:
        """Stop the bot and disconnect from all servers."""
        logger.info("Stopping Mattermost bot...")

        self._running = False

        # Cancel cache refresh
        if self._cache_refresh_task:
            self._cache_refresh_task.cancel()
            try:
                await self._cache_refresh_task
            except asyncio.CancelledError:
                pass

        # Cancel all websocket tasks
        for task in self._websocket_tasks.values():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Disconnect all drivers
        for tenant_id, driver in self._drivers.items():
            try:
                driver.disconnect()
                logger.info(f"Disconnected from tenant {tenant_id}")
            except Exception as e:
                logger.warning(f"Error disconnecting tenant {tenant_id}: {e}")

        self._drivers.clear()
        self._driver_wrappers.clear()
        self._websocket_tasks.clear()

        # Close API client
        await self.api_client.close()

        # Shutdown executor
        self._executor.shutdown(wait=False)

        # Clear cache
        self.cache.clear()

        logger.info("Mattermost bot stopped")

    async def _periodic_cache_refresh(self) -> None:
        """Background task to refresh cache and reconnect new servers."""
        while self._running:
            await asyncio.sleep(CACHE_REFRESH_INTERVAL)
            try:
                await self.cache.refresh_all()
                await self._connect_all_servers()
            except Exception as e:
                logger.error(f"Cache refresh failed: {e}")

    async def _connect_all_servers(self) -> None:
        """Connect to all Mattermost servers in the cache."""
        tenants = self.cache.get_all_tenants_with_bots()

        for tenant_id, server_url, bot_token in tenants:
            if tenant_id in self._drivers:
                continue  # Already connected

            try:
                await self._connect_server(tenant_id, server_url, bot_token)
            except Exception as e:
                logger.error(f"Failed to connect to tenant {tenant_id}: {e}")

    async def _connect_server(
        self, tenant_id: str, server_url: str, bot_token: str
    ) -> None:
        """Connect to a single Mattermost server."""
        logger.info(f"Connecting to Mattermost server for tenant {tenant_id}: {server_url}")

        # Parse server URL
        # Expected format: https://mattermost.example.com or http://localhost:8065
        url_parts = server_url.replace("https://", "").replace("http://", "")
        scheme = "https" if server_url.startswith("https") else "http"

        # Check for port
        if ":" in url_parts:
            host, port_str = url_parts.split(":", 1)
            port = int(port_str.rstrip("/"))
        else:
            host = url_parts.rstrip("/")
            port = 443 if scheme == "https" else 80

        # Create driver
        driver = Driver({
            "url": host,
            "token": bot_token,
            "scheme": scheme,
            "port": port,
            "verify": True,  # SSL verification
        })

        # Login (validates token)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._executor, driver.login)

        # Get bot user ID
        me = await loop.run_in_executor(self._executor, driver.users.get_user, "me")
        bot_user_id = me.get("id", "")

        # Store driver and wrapper
        self._drivers[tenant_id] = driver
        self._driver_wrappers[tenant_id] = MattermostDriverImpl(driver, self._executor)
        self._bot_user_ids[tenant_id] = bot_user_id

        logger.info(
            f"Connected to {server_url} as bot user {me.get('username')} ({bot_user_id})"
        )

        # Start websocket listener
        self._websocket_tasks[tenant_id] = asyncio.create_task(
            self._websocket_listener(tenant_id, driver)
        )

    async def _websocket_listener(self, tenant_id: str, driver: Driver) -> None:
        """WebSocket event listener for a single server.

        Handles reconnection on disconnect.
        """
        reconnect_attempts = 0

        while self._running and reconnect_attempts < MAX_RECONNECT_ATTEMPTS:
            try:
                logger.info(f"Starting WebSocket listener for tenant {tenant_id}")

                # Create event handler closure
                async def event_handler(event_str: str) -> None:
                    await self._handle_event(tenant_id, event_str)

                # init_websocket blocks until disconnected
                # Run in executor since it's blocking
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    self._executor,
                    lambda: driver.init_websocket(event_handler),
                )

                # If we get here, websocket disconnected normally
                logger.info(f"WebSocket disconnected for tenant {tenant_id}")
                reconnect_attempts = 0  # Reset on clean disconnect

            except Exception as e:
                reconnect_attempts += 1
                logger.error(
                    f"WebSocket error for tenant {tenant_id} "
                    f"(attempt {reconnect_attempts}/{MAX_RECONNECT_ATTEMPTS}): {e}"
                )

                if reconnect_attempts < MAX_RECONNECT_ATTEMPTS:
                    await asyncio.sleep(RECONNECT_DELAY * reconnect_attempts)

        if reconnect_attempts >= MAX_RECONNECT_ATTEMPTS:
            logger.error(
                f"Max reconnect attempts reached for tenant {tenant_id}, giving up"
            )

    async def _handle_event(self, tenant_id: str, event_str: str) -> None:
        """Handle a WebSocket event from Mattermost.

        Event format:
        {
            "event": "posted",
            "data": {
                "post": "{...json...}",
                "mentions": "[...]",
                "sender_name": "@username",
                "team_id": "...",
                ...
            },
            ...
        }
        """
        try:
            event = json.loads(event_str)
            event_type = event.get("event")

            # Only handle posted events
            if event_type != "posted":
                return

            # Parse message
            message = MattermostMessage.from_websocket_event(event)

            # Skip bot's own messages
            bot_user_id = self._bot_user_ids.get(tenant_id, "")
            if message.user_id == bot_user_id:
                return

            # Skip empty messages
            if not message.message.strip():
                return

            # Check if we should respond
            respond_context = await should_respond(message, tenant_id, bot_user_id)

            if not respond_context.should_respond:
                return

            logger.debug(
                f"Processing message: '{message.message[:50]}...' "
                f"from @{message.username} in channel {message.channel_id}"
            )

            # Get API key
            api_key = self.cache.get_api_key(tenant_id)
            if not api_key:
                logger.warning(f"No API key for tenant {tenant_id}")
                return

            # Get driver wrapper
            driver_wrapper = self._driver_wrappers.get(tenant_id)
            if not driver_wrapper:
                logger.warning(f"No driver wrapper for tenant {tenant_id}")
                return

            # Process message
            await process_chat_message(
                message=message,
                api_key=api_key,
                persona_id=respond_context.persona_id,
                thread_only_mode=respond_context.thread_only_mode,
                api_client=self.api_client,
                mm_driver=driver_wrapper,
                bot_user_id=bot_user_id,
            )

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse WebSocket event: {e}")
        except Exception as e:
            logger.exception(f"Error handling event: {e}")


# -----------------------------------------------------------------------------
# Entry Point
# -----------------------------------------------------------------------------


def main() -> None:
    """Main entry point for Mattermost bot."""
    from onyx.db.engine.sql_engine import SqlEngine
    from onyx.utils.variable_functionality import set_is_ee_based_on_env_variable

    logger.info("Starting Onyx Mattermost Bot...")

    # Initialize the database engine
    SqlEngine.init_engine(pool_size=20, max_overflow=5)

    # Initialize EE features
    set_is_ee_based_on_env_variable()

    # Create and run bot
    bot = OnyxMattermostBot()

    async def run_bot() -> None:
        await bot.start()

        # Keep running until interrupted
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await bot.stop()

    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Bot interrupted by user")
    except Exception:
        logger.exception("Fatal error in Mattermost bot")
        raise


if __name__ == "__main__":
    main()
