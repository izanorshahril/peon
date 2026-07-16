"""Provider-neutral values used by the agent runtime."""

from dataclasses import dataclass, field
from typing import Literal

MessageRole = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class AgentMessage:
    role: MessageRole
    content: str


@dataclass(frozen=True, slots=True)
class ModelResponse:
    content: str


@dataclass(slots=True)
class AgentContext:
    messages: list[AgentMessage] = field(default_factory=list)

    def add(self, message: AgentMessage) -> None:
        self.messages.append(message)