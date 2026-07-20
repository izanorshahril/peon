"""Direct Python adapter for host-neutral coding sessions."""

from collections.abc import Callable
import time
from typing import TypeAlias
from uuid import uuid4

from peon.agent import AgentContext, AgentMessage, ModelProvider, ToolExecutor
from peon.app.coding_session import (
    CodingSession,
    MessageEvent,
    SessionEvent,
    TurnFinishedEvent,
    TurnResult,
    TurnStartedEvent,
)
from peon.app.resources import ResourceInventory
from peon.app.sessions import MemorySessionStore, SessionStore

SessionEventHandler: TypeAlias = Callable[[SessionEvent], None]


class EmbeddedSession:
    """Submit text prompts without starting a terminal presentation host."""

    def __init__(
        self,
        *,
        provider: ModelProvider,
        session_store: SessionStore | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
        context: AgentContext | None = None,
        tools: ToolExecutor | None = None,
        model: str | None = None,
        resources: ResourceInventory | None = None,
        on_event: SessionEventHandler | None = None,
        clock: Callable[[], float] = time.monotonic,
        id_factory: Callable[[], str] = lambda: uuid4().hex,
    ) -> None:
        active_store = session_store or MemorySessionStore()
        active_session_id = session_id
        if active_session_id is None:
            active_session_id = active_store.create().session_id
        self._session = CodingSession(
            provider=provider,
            session_store=active_store,
            session_id=active_session_id,
            run_id=run_id,
            context=context,
            executor=tools,
            model=model,
            resources=resources,
            on_event=on_event,
            clock=clock,
            id_factory=id_factory,
        )

    @property
    def session_id(self) -> str:
        return self._session.session_id

    @property
    def run_id(self) -> str:
        return self._session.run_id

    @property
    def messages(self) -> tuple[AgentMessage, ...]:
        return self._session.messages

    def submit(self, text: str) -> TurnResult:
        """Submit one text prompt and return its structured turn result."""
        return self._session.prompt(text)

    def cancel(self) -> bool:
        """Request cancellation of the active prompt, if one is running."""
        return self._session.cancel()


__all__ = [
    "EmbeddedSession",
    "MessageEvent",
    "SessionEvent",
    "TurnFinishedEvent",
    "TurnResult",
    "TurnStartedEvent",
]