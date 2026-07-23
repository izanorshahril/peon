"""Errors raised by the portable agent runtime."""


class AgentError(Exception):
    """Base error for failures at the agent boundary."""


class LimitExceededError(AgentError):
    """Raised when a run limit is exceeded."""

    def __init__(self, stop_reason: str, message: str) -> None:
        super().__init__(message)
        self.stop_reason = stop_reason
