"""Safe exceptions raised by deterministic mock providers."""


class MockProviderInputError(ValueError):
    """Report invalid provider input without any external-service details."""

    def __init__(self, provider: str, message: str) -> None:
        self.provider = provider
        super().__init__(message)
