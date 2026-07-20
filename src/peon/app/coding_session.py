"""Host-neutral coding-session behavior."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from threading import Lock
import time
from typing import Literal, TypeAlias
from uuid import uuid4

from peon.agent import (
    AgentContext,
    AgentError,
    AgentMessage,
    ModelProvider,
    ToolCall,
    ToolExecutionContext,
    ToolExecutor,
    run_task,
)

from .resources import (
    ResourceInventory,
    apply_resource_prompt,
    conversation_messages_without_resource_prompt,
)
from .sessions import SessionStore, SessionStoreError

TurnStatus = Literal["success", "error", "cancelled"]


@dataclass(frozen=True, slots=True)
class TurnResult:
    status: TurnStatus
    session_id: str
    run_id: str
    turn_id: str
    content: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class TurnStartedEvent:
    session_id: str
    run_id: str
    turn_id: str
    started_at: float


@dataclass(frozen=True, slots=True)
class MessageEvent:
    session_id: str
    run_id: str
    turn_id: str
    message: AgentMessage


@dataclass(frozen=True, slots=True)
class TurnFinishedEvent:
    session_id: str
    run_id: str
    turn_id: str
    result: TurnResult
    duration: float


SessionEvent: TypeAlias = (
    TurnStartedEvent | MessageEvent | TurnFinishedEvent
)
EventHandler = Callable[[SessionEvent], None]
logger = logging.getLogger(__name__)


class CodingSession:
    """Run and persist coding turns independently of a presentation host."""

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
        clock: Callable[[], float] = time.monotonic,
        id_factory: Callable[[], str] = lambda: uuid4().hex,
    ) -> None:
        self.provider = provider
        self.session_store = session_store
        self._session_id = session_id
        self._run_id = run_id or uuid4().hex
        self._context = context or AgentContext()
        self._executor = executor
        self._model = model
        self._resources = resources
        if resources is not None:
            apply_resource_prompt(self._context, resources)
        self._on_event = on_event
        self._clock = clock
        self._id_factory = id_factory
        self._active_execution_context: ToolExecutionContext | None = None
        self._state_lock = Lock()

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def messages(self) -> tuple[AgentMessage, ...]:
        """Return conversation messages without generated resource prompts."""
        return conversation_messages_without_resource_prompt(
            self._context.messages,
            self._resources,
        )

    def prompt(
        self,
        task: str,
        *,
        preserve_task_whitespace: bool = False,
    ) -> TurnResult:
        """Run one prompt and return a structured terminal outcome."""
        execution_context = ToolExecutionContext()
        turn_id = self._id_factory()
        with self._state_lock:
            if self._active_execution_context is not None:
                return TurnResult(
                    status="error",
                    session_id=self._session_id,
                    run_id=self._run_id,
                    turn_id=turn_id,
                    error="session is already running",
                )
            self._active_execution_context = execution_context

        started_at = self._clock()
        try:
            self._emit(
                TurnStartedEvent(
                    session_id=self._session_id,
                    run_id=self._run_id,
                    turn_id=turn_id,
                    started_at=started_at,
                )
            )
            try:
                response = run_task(
                    task,
                    self.provider,
                    context=self._context,
                    executor=self._executor,
                    model=self._model,
                    on_message=lambda message: self._persist_message(
                        message,
                        turn_id,
                    ),
                    preserve_task_whitespace=preserve_task_whitespace,
                    execution_context=execution_context,
                )
            except Exception as error:
                result = TurnResult(
                    status=(
                        "cancelled"
                        if execution_context.cancelled
                        else "error"
                    ),
                    session_id=self._session_id,
                    run_id=self._run_id,
                    turn_id=turn_id,
                    error=str(error),
                )
            else:
                if execution_context.cancelled:
                    result = TurnResult(
                        status="cancelled",
                        session_id=self._session_id,
                        run_id=self._run_id,
                        turn_id=turn_id,
                        error="task cancelled",
                    )
                elif isinstance(response, ToolCall):
                    result = TurnResult(
                        status="error",
                        session_id=self._session_id,
                        run_id=self._run_id,
                        turn_id=turn_id,
                        error=(
                            f"provider requested tool '{response.name}', but "
                            "tool execution is not configured"
                        ),
                    )
                else:
                    result = TurnResult(
                        status="success",
                        session_id=self._session_id,
                        run_id=self._run_id,
                        turn_id=turn_id,
                        content=response,
                    )
            self._emit(
                TurnFinishedEvent(
                    session_id=self._session_id,
                    run_id=self._run_id,
                    turn_id=turn_id,
                    result=result,
                    duration=self._clock() - started_at,
                )
            )
            return result
        finally:
            with self._state_lock:
                self._active_execution_context = None

    def cancel(self) -> bool:
        """Request cancellation of the active provider/tool turn."""
        with self._state_lock:
            execution_context = self._active_execution_context
        if execution_context is None:
            return False
        execution_context.cancel()
        return True

    def _persist_message(self, message: AgentMessage, turn_id: str) -> None:
        self.session_store.append(self._session_id, message)
        self._emit(
            MessageEvent(
                session_id=self._session_id,
                run_id=self._run_id,
                turn_id=turn_id,
                message=message,
            )
        )

    def _emit(self, event: SessionEvent) -> None:
        if self._on_event is not None:
            try:
                self._on_event(event)
            except Exception:
                logger.exception("coding session event handler failed")
                return
