"""Provider-neutral tool execution contract."""

from collections.abc import Mapping, Sequence
from typing import Protocol

from .models import ToolDefinition


class ToolExecutor(Protocol):
    @property
    def tools(self) -> Sequence[ToolDefinition]:
        """Return model-facing definitions for executable tools."""
        ...

    def invoke(self, name: str, arguments: Mapping[str, object]) -> str:
        """Execute a named tool and return its text result."""
        ...