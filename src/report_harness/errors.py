"""Errors raised at the harness's public seams."""


class HarnessError(Exception):
    """Base error for expected harness failures."""


class WorkbookSchemaError(HarnessError):
    """The workbook does not provide the required report columns."""


class EvidenceResolutionError(HarnessError):
    """A row's evidence reference cannot be resolved."""


class ProviderError(HarnessError):
    """A provider cannot produce a normalized response."""


class CommandError(HarnessError):
    """A command request is invalid or cannot be completed."""