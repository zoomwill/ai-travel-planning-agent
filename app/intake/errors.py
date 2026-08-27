"""Stable conversational-intake failures safe for HTTP responses."""


class IntakeError(Exception):
    """Carry one stable public code without preserving private exception text."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class IntakeConflictError(IntakeError):
    """Report a valid request that conflicts with current intake state."""


class IntakeNotFoundError(IntakeError):
    """Report that no intake exists in the requested user namespace."""


class IntakeUnavailableError(IntakeError):
    """Report an unavailable Store or structured extraction provider."""
