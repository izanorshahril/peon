"""Public data contracts for the report-generation workflow."""

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class WorkbookRow:
	"""A workbook item exposed to the evidence and provider adapters."""

	row_number: int
	evidence_reference: str | None
	values: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceEnvelope:
	"""Evidence normalized for provider adapters."""

	reference: str
	media_type: str
	content: bytes
	metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderRequest:
	"""Normalized request sent to a justification provider."""

	row_number: int
	evidence: EvidenceEnvelope
	instructions: str = ""


@dataclass(frozen=True)
class ProviderResponse:
	"""Normalized answer and justification returned by a provider."""

	answer: str
	justification: str
