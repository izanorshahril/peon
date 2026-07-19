"""Provider-neutral tool execution contract."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from threading import Event
from typing import Protocol

from .models import ToolDefinition


@dataclass(slots=True)
class ToolExecutionContext:
    """Cancellation and bounded output hooks for one tool operation."""

    on_output: Callable[[str, str], None] | None = None
    _cancelled: Event = field(default_factory=Event, init=False, repr=False)

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def cancel(self) -> None:
        self._cancelled.set()


class ToolExecutor(Protocol):
    @property
    def tools(self) -> Sequence[ToolDefinition]:
        """Return model-facing definitions for executable tools."""
        ...

    def invoke(self, name: str, arguments: Mapping[str, object]) -> str:
        """Execute a named tool and return its text result."""
        ...

