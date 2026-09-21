"""Errors shared by inference factories."""


class UnsupportedProviderError(ValueError):
    """The configured provider does not implement the requested capability."""

    def __init__(self, capability: str, provider: str) -> None:
        super().__init__(f"Unsupported {capability} provider: {provider}")
        self.capability = capability
        self.provider = provider
