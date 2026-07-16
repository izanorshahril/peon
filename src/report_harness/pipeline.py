"""Core orchestration for the report-generation workflow."""

from pathlib import Path
from typing import Protocol

from .models import EvidenceEnvelope, ProviderRequest, ProviderResponse, WorkbookRow


class WorkbookPort(Protocol):
    def iter_rows(self): ...

    def write_result(self, row_number: int, response: ProviderResponse) -> None: ...

    def save(self, path: Path | str | None = None) -> Path: ...


class EvidencePort(Protocol):
    def resolve(self, row: WorkbookRow) -> EvidenceEnvelope: ...


class ProviderPort(Protocol):
    def justify(self, request: ProviderRequest) -> ProviderResponse: ...


class ReportRunner:
    """Coordinate adapters without knowing their source or provider details."""

    def __init__(
        self,
        workbook: WorkbookPort,
        evidence: EvidencePort,
        provider: ProviderPort,
        instructions: str = "",
    ) -> None:
        self.workbook = workbook
        self.evidence = evidence
        self.provider = provider
        self.instructions = instructions

    def run(self, output_path: Path | str | None = None) -> Path:
        for row in self.workbook.iter_rows():
            evidence = self.evidence.resolve(row)
            response = self.provider.justify(
                ProviderRequest(
                    row_number=row.row_number,
                    evidence=evidence,
                    instructions=self.instructions,
                )
            )
            self.workbook.write_result(row.row_number, response)
        return self.workbook.save(output_path)