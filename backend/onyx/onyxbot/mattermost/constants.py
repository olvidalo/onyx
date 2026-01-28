"""Mattermost bot constants."""

# API settings
API_REQUEST_TIMEOUT: int = 3 * 60  # 3 minutes

# Cache settings
CACHE_REFRESH_INTERVAL: int = 60  # 1 minute

# Message settings
MAX_MESSAGE_LENGTH: int = 16383  # Mattermost's max post length
MAX_CONTEXT_MESSAGES: int = 10  # Max messages to include in conversation context

# Emoji reactions (Mattermost uses text names, not Unicode)
THINKING_EMOJI: str = "hourglass_flowing_sand"
SUCCESS_EMOJI: str = "white_check_mark"
ERROR_EMOJI: str = "x"

# Command prefix (Mattermost uses slash commands or bot mentions)
REGISTER_COMMAND: str = "register"
SYNC_CHANNELS_COMMAND: str = "sync-channels"

# WebSocket reconnection settings
RECONNECT_DELAY: int = 5  # seconds
MAX_RECONNECT_ATTEMPTS: int = 10
