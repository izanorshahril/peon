from pathlib import Path

import pytest

from report_harness.errors import EvidenceResolutionError
from report_harness.evidence import ImageEvidenceResolver
from report_harness.models import WorkbookRow


def test_resolves_relative_image_reference_to_normalized_evidence(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "evidence.png"
    image_path.write_bytes(b"png-bytes")
    resolver = ImageEvidenceResolver(base_dir=tmp_path)

    evidence = resolver.resolve(
        WorkbookRow(row_number=2, evidence_reference="evidence.png")
    )

    assert evidence.reference == str(image_path)
    assert evidence.media_type == "image/png"
    assert evidence.content == b"png-bytes"


def test_missing_image_reference_identifies_the_row(tmp_path: Path) -> None:
    resolver = ImageEvidenceResolver(base_dir=tmp_path)

    with pytest.raises(EvidenceResolutionError, match="row 4"):
        resolver.resolve(WorkbookRow(row_number=4, evidence_reference="missing.png"))


def test_empty_image_reference_identifies_the_row(tmp_path: Path) -> None:
    resolver = ImageEvidenceResolver(base_dir=tmp_path)

    with pytest.raises(EvidenceResolutionError, match="row 6"):
        resolver.resolve(WorkbookRow(row_number=6, evidence_reference=None))


def test_resolves_http_image_reference_through_injected_fetcher() -> None:
    resolver = ImageEvidenceResolver(
        fetcher=lambda reference: (b"remote-image", "image/jpeg")
    )

    evidence = resolver.resolve(
        WorkbookRow(row_number=5, evidence_reference="https://example.test/image.jpg")
    )

    assert evidence.reference == "https://example.test/image.jpg"
    assert evidence.media_type == "image/jpeg"
    assert evidence.content == b"remote-image"
