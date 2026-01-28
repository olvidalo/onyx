"""Mattermost bot message handling and response logic."""

import asyncio
import json
from dataclasses import dataclass

from pydantic import BaseModel

from onyx.chat.models import ChatFullResponse
from onyx.db.mattermost_bot import get_channel_config_by_mattermost_ids
from onyx.db.mattermost_bot import get_team_config_by_mattermost_id
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.models import MattermostChannelConfig
from onyx.db.models import MattermostTeamConfig
from onyx.onyxbot.mattermost.api_client import OnyxAPIClient
from onyx.onyxbot.mattermost.constants import MAX_CONTEXT_MESSAGES
from onyx.onyxbot.mattermost.constants import MAX_MESSAGE_LENGTH
from onyx.onyxbot.mattermost.constants import THINKING_EMOJI
from onyx.onyxbot.mattermost.exceptions import APIError
from onyx.utils.logger import setup_logger

logger = setup_logger()


class ShouldRespondContext(BaseModel):
    """Context for whether the bot should respond to a message."""

    should_respond: bool
    persona_id: int | None
    thread_only_mode: bool


@dataclass
class MattermostMessage:
    """Parsed Mattermost WebSocket 'posted' event data.

    The WebSocket event structure has nested JSON:
    - data.post is a JSON-encoded string containing the post object
    - data.mentions is a JSON-encoded array of user IDs
    """

    post_id: str
    channel_id: str
    team_id: str
    user_id: str
    username: str  # From sender_name in event data
    message: str
    root_id: str  # Empty string if not in thread, parent post ID if reply
    mentions: list[str]  # List of mentioned user IDs

    @property
    def is_thread(self) -> bool:
        """Check if this message is part of a thread."""
        return bool(self.root_id)

    @classmethod
    def from_websocket_event(cls, event_data: dict) -> "MattermostMessage":
        """Parse a WebSocket 'posted' event into a MattermostMessage.

        The event structure:
        {
            "event": "posted",
            "data": {
                "post": "{...json...}",  # JSON-encoded post object
                "mentions": "[...]",      # JSON-encoded array of user IDs
                "sender_name": "@username",
                "team_id": "...",
                ...
            },
            ...
        }
        """
        data = event_data.get("data", {})

        # Parse nested JSON for post
        post_json = data.get("post", "{}")
        post = json.loads(post_json) if isinstance(post_json, str) else post_json

        # Parse nested JSON for mentions
        mentions_json = data.get("mentions", "[]")
        mentions = (
            json.loads(mentions_json) if isinstance(mentions_json, str) else mentions_json
        ) or []

        # Extract sender name (remove @ prefix if present)
        sender_name = data.get("sender_name", "")
        if sender_name.startswith("@"):
            sender_name = sender_name[1:]

        return cls(
            post_id=post.get("id", ""),
            channel_id=post.get("channel_id", ""),
            team_id=data.get("team_id", ""),
            user_id=post.get("user_id", ""),
            username=sender_name,
            message=post.get("message", ""),
            root_id=post.get("root_id", ""),  # Empty string if not in thread
            mentions=mentions,
        )


# -------------------------------------------------------------------------
# Response Logic
# -------------------------------------------------------------------------


async def should_respond(
    message: MattermostMessage,
    tenant_id: str,
    bot_user_id: str,
) -> ShouldRespondContext:
    """Determine if bot should respond and which persona to use."""
    team_id = message.team_id
    channel_id = message.channel_id
    bot_mentioned = bot_user_id in message.mentions

    def _get_configs() -> (
        tuple[MattermostTeamConfig | None, MattermostChannelConfig | None]
    ):
        with get_session_with_tenant(tenant_id=tenant_id) as db:
            team_config = get_team_config_by_mattermost_id(db, team_id)
            if not team_config or not team_config.enabled:
                return None, None

            channel_config = get_channel_config_by_mattermost_ids(
                db, team_id, channel_id
            )
            return team_config, channel_config

    team_config, channel_config = await asyncio.to_thread(_get_configs)

    if not team_config or not channel_config or not channel_config.enabled:
        return ShouldRespondContext(
            should_respond=False, persona_id=None, thread_only_mode=False
        )

    # Determine persona (channel override or team default)
    persona_id = channel_config.persona_override_id or team_config.default_persona_id

    # Check mention requirement (with exceptions for implicit invocation)
    if channel_config.require_bot_invocation and not bot_mentioned:
        if not await check_implicit_invocation(message, bot_user_id):
            return ShouldRespondContext(
                should_respond=False, persona_id=None, thread_only_mode=False
            )

    return ShouldRespondContext(
        should_respond=True,
        persona_id=persona_id,
        thread_only_mode=channel_config.thread_only_mode,
    )


async def check_implicit_invocation(
    message: MattermostMessage,
    bot_user_id: str,
) -> bool:
    """Check if the bot should respond without explicit mention.

    Returns True if user is in a thread (implicit continuation of conversation).
    """
    if message.is_thread:
        logger.debug(f"Implicit invocation via thread: '{message.message[:50]}...'")
        return True

    return False


# -------------------------------------------------------------------------
# Message Processing
# -------------------------------------------------------------------------


async def process_chat_message(
    message: MattermostMessage,
    api_key: str,
    persona_id: int | None,
    thread_only_mode: bool,
    api_client: OnyxAPIClient,
    mm_driver: "MattermostDriverWrapper",
    bot_user_id: str,
) -> None:
    """Process a message and send response."""
    # Add thinking reaction
    try:
        await mm_driver.add_reaction(message.post_id, THINKING_EMOJI, bot_user_id)
    except Exception:
        logger.warning(
            f"Failed to add thinking reaction to message: '{message.message[:50]}...'"
        )

    try:
        # Build conversation context
        context = await _build_conversation_context(message, mm_driver, bot_user_id)

        # Prepare full message content
        parts = []
        if context:
            parts.append(context)
        parts.append(f"Current message from @{message.username}: {message.message}")

        # Send to API
        response = await api_client.send_chat_message(
            message="\n\n".join(parts),
            api_key=api_key,
            persona_id=persona_id,
        )

        # Format response with citations
        answer = response.answer or "I couldn't generate a response."
        answer = _append_citations(answer, response)

        await send_response(message, answer, thread_only_mode, mm_driver)

        # Remove thinking reaction
        try:
            await mm_driver.remove_reaction(message.post_id, THINKING_EMOJI, bot_user_id)
        except Exception:
            pass

    except APIError as e:
        logger.error(f"API error processing message: {e}")
        await send_error_response(message, mm_driver, bot_user_id)
    except Exception as e:
        logger.exception(f"Error processing chat message: {e}")
        await send_error_response(message, mm_driver, bot_user_id)


async def _build_conversation_context(
    message: MattermostMessage,
    mm_driver: "MattermostDriverWrapper",
    bot_user_id: str,
) -> str | None:
    """Build conversation context from thread history."""
    if message.is_thread and message.root_id:
        return await _build_thread_context(message, mm_driver, bot_user_id)
    return None


def _append_citations(answer: str, response: ChatFullResponse) -> str:
    """Append citation sources to the answer if present."""
    if not response.citation_info or not response.top_documents:
        return answer

    cited_docs: list[tuple[int, str, str | None]] = []
    for citation in response.citation_info:
        doc = next(
            (
                d
                for d in response.top_documents
                if d.document_id == citation.document_id
            ),
            None,
        )
        if doc:
            cited_docs.append(
                (
                    citation.citation_number,
                    doc.semantic_identifier or "Source",
                    doc.link,
                )
            )

    if not cited_docs:
        return answer

    cited_docs.sort(key=lambda x: x[0])
    citations = "\n\n**Sources:**\n"
    for num, name, link in cited_docs[:5]:
        if link:
            citations += f"{num}. [{name}]({link})\n"
        else:
            citations += f"{num}. {name}\n"

    return answer + citations


# -------------------------------------------------------------------------
# Context Building
# -------------------------------------------------------------------------


async def _build_thread_context(
    message: MattermostMessage,
    mm_driver: "MattermostDriverWrapper",
    bot_user_id: str,
) -> str | None:
    """Build context from thread message history."""
    if not message.root_id:
        return None

    try:
        # Get thread posts from Mattermost
        thread_data = await mm_driver.get_thread(message.root_id)

        if not thread_data:
            return None

        # thread_data contains 'order' (list of post IDs) and 'posts' (dict of posts)
        posts_dict = thread_data.get("posts", {})
        order = thread_data.get("order", [])

        # Format messages as context (limit to recent messages)
        formatted = []
        for post_id in order[-MAX_CONTEXT_MESSAGES:]:
            if post_id == message.post_id:
                continue  # Skip current message

            post = posts_dict.get(post_id, {})
            user_id = post.get("user_id", "")

            # Get username - we may need to look this up
            username = "unknown"
            if user_id == bot_user_id:
                username = "OnyxBot"
            else:
                # Use the message content author info if available
                username = f"user_{user_id[:8]}"

            formatted.append(f"{username}: {post.get('message', '')}")

        if not formatted:
            return None

        logger.debug(f"Built thread context: {len(formatted)} messages")

        return (
            "You are a Mattermost bot named OnyxBot.\n"
            'Always assume that [user] is the same as the "Current message" author.\n'
            "Conversation history:\n"
            "---\n" + "\n".join(formatted) + "\n---"
        )

    except Exception as e:
        logger.warning(f"Failed to build thread context: {e}")
        return None


# -------------------------------------------------------------------------
# Response Sending
# -------------------------------------------------------------------------


async def send_response(
    message: MattermostMessage,
    content: str,
    thread_only_mode: bool,
    mm_driver: "MattermostDriverWrapper",
) -> None:
    """Send response based on thread_only_mode setting."""
    chunks = _split_message(content)

    # Determine where to post
    if message.is_thread:
        # Reply in existing thread
        root_id = message.root_id
    elif thread_only_mode:
        # Create new thread from the original message
        root_id = message.post_id
    else:
        # Reply in channel (not as thread)
        root_id = ""

    for chunk in chunks:
        await mm_driver.create_post(
            channel_id=message.channel_id,
            message=chunk,
            root_id=root_id if root_id else None,
        )


def _split_message(content: str) -> list[str]:
    """Split content into chunks that fit Mattermost's message limit."""
    chunks = []
    while content:
        if len(content) <= MAX_MESSAGE_LENGTH:
            chunks.append(content)
            break

        # Find a good split point
        split_at = MAX_MESSAGE_LENGTH
        for sep in ["\n\n", "\n", ". ", " "]:
            idx = content.rfind(sep, 0, MAX_MESSAGE_LENGTH)
            if idx > MAX_MESSAGE_LENGTH // 2:
                split_at = idx + len(sep)
                break

        chunks.append(content[:split_at])
        content = content[split_at:]

    return chunks


async def send_error_response(
    message: MattermostMessage,
    mm_driver: "MattermostDriverWrapper",
    bot_user_id: str,
) -> None:
    """Send error response and clean up reaction."""
    try:
        await mm_driver.remove_reaction(message.post_id, THINKING_EMOJI, bot_user_id)
    except Exception:
        pass

    error_msg = "Sorry, I encountered an error processing your message. Please try again or contact your administrator."

    try:
        # Reply in thread if in thread, otherwise create thread
        root_id = message.root_id if message.is_thread else message.post_id
        await mm_driver.create_post(
            channel_id=message.channel_id,
            message=error_msg,
            root_id=root_id,
        )
    except Exception:
        pass


# -------------------------------------------------------------------------
# Mattermost Driver Wrapper Interface
# -------------------------------------------------------------------------


class MattermostDriverWrapper:
    """Wrapper interface for Mattermost driver operations.

    This wraps the synchronous mattermostdriver API to provide async methods
    that can be used by the message handlers.
    """

    async def add_reaction(
        self, post_id: str, emoji_name: str, user_id: str
    ) -> None:
        """Add a reaction to a post."""
        raise NotImplementedError

    async def remove_reaction(
        self, post_id: str, emoji_name: str, user_id: str
    ) -> None:
        """Remove a reaction from a post."""
        raise NotImplementedError

    async def create_post(
        self,
        channel_id: str,
        message: str,
        root_id: str | None = None,
    ) -> dict:
        """Create a new post in a channel."""
        raise NotImplementedError

    async def get_thread(self, post_id: str) -> dict:
        """Get all posts in a thread."""
        raise NotImplementedError

    async def get_user(self, user_id: str) -> dict:
        """Get user info by ID."""
        raise NotImplementedError
