"""Host-neutral session controller for prompt dispatch."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import time
from typing import TypeAlias
from uuid import uuid4

from peon.agent import (
    AgentContext,
    AgentMessage,
    ModelProvider,
    ToolExecutor,
    Usage,
)
from peon.agent.tracing import TraceSink

from .coding_session import (
    CodingSession,
    EventHandler,
    MessageEvent,
    SessionEvent,
    TurnFinishedEvent,
    TurnResult,
    TurnStartedEvent,
)
from .resources import ResourceInventory
from .sessions import SessionStore


@dataclass(frozen=True, slots=True)
class PromptIntent:
    """Typed prompt request for dispatch through the session controller."""

    text: str
    preserve_whitespace: bool = False


class SessionController:
    """Dispatch typed prompt intents through a host-neutral session boundary.

    Composes :class:`CodingSession` rather than duplicating the agent loop.
    Every host (one-shot CLI, print, JSONL, embedded, Textual, prompt-toolkit)
    dispatches prompts through this controller to get equivalent events, results,
    persistence, cancellation, and resource behavior.
    """

    def __init__(
        self,
        *,
        provider: ModelProvider,
        session_store: SessionStore,
        session_id: str,
        run_id: str | None = None,
        context: AgentContext | None = None,
        executor: ToolExecutor | None = None,
        model: str | None = None,
        resources: ResourceInventory | None = None,
        on_event: EventHandler | None = None,
        on_tool_output: Callable[[str, str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        id_factory: Callable[[], str] = lambda: uuid4().hex,
        trace_sink: TraceSink | None = None,
        trace_provider: str | None = None,
        trace_utc_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = CodingSession(
            provider=provider,
            session_store=session_store,
            session_id=session_id,
            run_id=run_id,
            context=context,
            executor=executor,
            model=model,
            resources=resources,
            on_event=on_event,
            on_tool_output=on_tool_output,
            clock=clock,
            id_factory=id_factory,
            trace_sink=trace_sink,
            trace_provider=trace_provider,
            trace_utc_clock=trace_utc_clock,
        )

    @property
    def session_id(self) -> str:
        return self._session.session_id

    @property
    def run_id(self) -> str:
        return self._session.run_id

    @property
    def messages(self) -> tuple[AgentMessage, ...]:
        """Return conversation messages without generated resource prompts."""
        return self._session.messages

    @property
    def session(self) -> CodingSession:
        """Direct access to the inner coding session.

        Exposed for hosts that need internal access during migration
        (e.g. Textual shell commands reaching the provider directly).
        """
        return self._session

    def dispatch(self, intent: PromptIntent) -> TurnResult:
        """Dispatch one typed prompt intent and return a structured outcome."""
        return self._session.prompt(
            intent.text,
            preserve_task_whitespace=intent.preserve_whitespace,
        )

    def cancel(self) -> bool:
        """Request cancellation of the active prompt, if one is running."""
        return self._session.cancel()
