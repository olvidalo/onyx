class ModelServerRateLimitError(Exception):
    """
    Exception raised for rate limiting errors from the model server.
    """


class CohereBillingLimitError(Exception):
    """
    Raised when Cohere rejects requests because the billing cap is reached.
    """


class EmbeddingRateLimitError(Exception):
    """
    Raised when embedding API returns 429 with Retry-After header.
    Carries the retry_after value so Celery can reschedule the task.
    """

    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after
