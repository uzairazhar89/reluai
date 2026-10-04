"""Provider error taxonomy. The chain falls through on everything except bad requests."""

from __future__ import annotations


class ProviderError(RuntimeError):
    """Base class; ``fall_through`` says whether the next provider should be tried."""

    fall_through = True
    outcome = "error"


class NotConfiguredError(ProviderError):
    outcome = "not_configured"


class RateLimitedError(ProviderError):
    outcome = "rate_limited"

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ProviderUnavailableError(ProviderError):
    outcome = "unavailable"


class BudgetExceededError(ProviderError):
    outcome = "budget_exhausted"


class BadRequestError(ProviderError):
    """The request itself is invalid; another provider would reject it too."""

    fall_through = False
    outcome = "bad_request"


class AllProvidersFailedError(RuntimeError):
    def __init__(self, attempts: list[object]) -> None:
        super().__init__("no provider produced a response")
        self.attempts = attempts
