"""Image evidence adapter for local files and HTTP(S) references."""

import mimetypes
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse

from .errors import EvidenceResolutionError
from .models import EvidenceEnvelope, WorkbookRow


ImageFetcher = Callable[[str], tuple[bytes, str]]


class ImageEvidenceResolver:
    """Resolve a workbook image reference into normalized evidence."""

    def __init__(
        self,
        base_dir: Path | str | None = None,
        fetcher: ImageFetcher | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_dir = Path(base_dir) if base_dir is not None else Path.cwd()
        self.fetcher = fetcher
        self.timeout = timeout

    def resolve(self, row: WorkbookRow) -> EvidenceEnvelope:
        reference = row.evidence_reference
        if not reference:
            raise EvidenceResolutionError(
                f"Missing image reference for row {row.row_number}"
            )
        try:
            if urlparse(reference).scheme in {"http", "https"}:
                content, media_type = self._resolve_url(reference)
                resolved_reference = reference
            else:
                path = self._resolve_path(reference)
                content = path.read_bytes()
                media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                resolved_reference = str(path)
        except (OSError, HTTPError, URLError, ValueError) as error:
            raise EvidenceResolutionError(
                f"Unable to resolve image reference for row {row.row_number}: "
                f"{reference}"
            ) from error
        return EvidenceEnvelope(
            reference=resolved_reference,
            media_type=media_type,
            content=content,
        )

    def _resolve_path(self, reference: str) -> Path:
        path = Path(reference)
        if not path.is_absolute():
            path = self.base_dir / path
        if not path.is_file():
            raise FileNotFoundError(reference)
        return path.resolve()

    def _resolve_url(self, reference: str) -> tuple[bytes, str]:
        if self.fetcher is not None:
            return self.fetcher(reference)
        request = Request(reference, headers={"User-Agent": "report-generation-harness"})
        with urlopen(request, timeout=self.timeout) as response:
            content_type = response.headers.get_content_type()
            return response.read(), content_type
