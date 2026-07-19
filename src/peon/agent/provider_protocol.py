"""Provider protocol consumed by the portable agent runtime."""

from collections.abc import Sequence
from typing import Protocol

from .models import AgentMessage, ModelResponse, ToolDefinition


class ModelProvider(Protocol):
    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        """Return one normalized model response for the current context."""