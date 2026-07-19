"""Errors raised by model provider adapters."""


class ProviderError(Exception):
    """A provider cannot produce a normalized model response."""