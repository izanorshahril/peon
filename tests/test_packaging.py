"""Tests for packaging, optional extras isolation, and host availability."""

import sys
from pathlib import Path
import pytest


def test_clean_base_imports_do_not_require_tui_or_serve_modules() -> None:
    """Verify that core agent, AI, controller, embedded, and CLI modules can be imported

    without pulling in Textual or textual-serve frontend dependencies.
    """
    # Import core public modules
    import peon.agent
    import peon.ai
    import peon.embedded
    from peon.app.session_controller import SessionController
    from peon.app.cli import main

    assert peon.agent is not None
    assert peon.ai is not None
    assert peon.embedded is not None
    assert SessionController is not None
    assert main is not None

    # Frontend packages should not be loaded by base imports alone
    assert "textual_serve" not in sys.modules
    assert "prompt_toolkit" not in sys.modules


def test_missing_tui_extra_returns_actionable_error_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify resolve_host('textual') produces an actionable error without traceback when Textual is missing."""
    from peon.app.hosts import resolve_host, HostUnavailableError

    # Simulate missing textual package
    monkeypatch.setitem(sys.modules, "textual", None)

    with pytest.raises(HostUnavailableError, match="peon\\[tui\\]"):
        resolve_host("textual")


def test_pyproject_metadata_floor_and_extras() -> None:
    """Verify pyproject.toml declares Python >=3.13, empty base dependencies, and tui/serve extras."""
    pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
    assert pyproject_path.exists()
    content = pyproject_path.read_text(encoding="utf-8")

    assert 'requires-python = ">=3.13"' in content
    assert "dependencies = []" in content
    assert "tui = [" in content
    assert "serve = [" in content
    assert "textual-serve>=1.0.0" in content
