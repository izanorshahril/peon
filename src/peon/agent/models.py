"""Provider-neutral values used by the agent runtime."""

from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Literal

MessageRole = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class AgentMessage:
    role: MessageRole
    content: str


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    arguments: Mapping[str, object]
    call_id: str | None = None


@dataclass(frozen=True, slots=True)
class ModelResponse:
    content: str = ""
    tool_call: ToolCall | None = None


@dataclass(slots=True)
class AgentContext:
    messages: list[AgentMessage] = field(default_factory=list)

    def add(self, message: AgentMessage) -> None:
        self.messages.append(message)