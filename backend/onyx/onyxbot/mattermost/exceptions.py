"""Custom exception classes for Mattermost bot."""


class MattermostBotError(Exception):
    """Base exception for Mattermost bot errors."""


class RegistrationError(MattermostBotError):
    """Error during team registration."""


class SyncChannelsError(MattermostBotError):
    """Error during channel sync."""


class APIError(MattermostBotError):
    """Base API error."""


class CacheError(MattermostBotError):
    """Error during cache operations."""


class APIConnectionError(APIError):
    """Failed to connect to API."""


class APITimeoutError(APIError):
    """Request timed out."""


class APIResponseError(APIError):
    """API returned an error response."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class WebSocketError(MattermostBotError):
    """WebSocket connection error."""
