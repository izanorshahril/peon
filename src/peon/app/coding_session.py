"""Host-neutral coding-session behavior."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
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
    Usage,
    run_task,
)
from peon.agent.tracing import TraceContext, TraceSink, emit_trace

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
    usage: Usage | None = None


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


class _UsageAccumulator:
    def __init__(self) -> None:
        self._input_tokens = 0
        self._output_tokens = 0
        self._cache_tokens = 0
        self._has_input_tokens = False
        self._has_output_tokens = False
        self._has_cache_tokens = False
        self._cost_by_currency: dict[str | None, float] = {}
        self._currencies: set[str] = set()

    def add(self, usage: Usage | None) -> None:
        if usage is None:
            return
        if usage.input_tokens is not None:
            self._input_tokens += usage.input_tokens
            self._has_input_tokens = True
        if usage.output_tokens is not None:
            self._output_tokens += usage.output_tokens
            self._has_output_tokens = True
        if usage.cache_tokens is not None:
            self._cache_tokens += usage.cache_tokens
            self._has_cache_tokens = True
        if usage.cost is not None:
            self._cost_by_currency[usage.currency] = (
                self._cost_by_currency.get(usage.currency, 0.0) + usage.cost
            )
        if usage.currency is not None:
            self._currencies.add(usage.currency)

    def result(self) -> Usage | None:
        if not any(
            (
                self._has_input_tokens,
                self._has_output_tokens,
                self._has_cache_tokens,
                self._cost_by_currency,
                self._currencies,
            )
        ):
            return None
        cost_currency = None
        cost = None
        if len(self._cost_by_currency) == 1:
            cost_currency, cost = next(iter(self._cost_by_currency.items()))
        return Usage(
            input_tokens=self._input_tokens if self._has_input_tokens else None,
            output_tokens=self._output_tokens if self._has_output_tokens else None,
            cache_tokens=self._cache_tokens if self._has_cache_tokens else None,
            cost=cost,
            currency=(
                cost_currency
                if cost is not None
                else (
                    next(iter(self._currencies))
                    if len(self._currencies) == 1
                    else None
                )
            ),
        )


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
        on_tool_output: Callable[[str, str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        id_factory: Callable[[], str] = lambda: uuid4().hex,
        trace_sink: TraceSink | None = None,
        trace_provider: str | None = None,
        trace_utc_clock: Callable[[], datetime] | None = None,
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
        self._on_tool_output = on_tool_output
        self._clock = clock
        self._id_factory = id_factory
        self._trace_sink = trace_sink
        self._trace_provider = trace_provider
        self._trace_utc_clock = trace_utc_clock
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
        execution_context = ToolExecutionContext(on_output=self._on_tool_output)
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
        usage = _UsageAccumulator()
        trace_context = TraceContext(
            session_id=self._session_id,
            run_id=self._run_id,
            turn_id=turn_id,
        )
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
                    on_usage=usage.add,
                    preserve_task_whitespace=preserve_task_whitespace,
                    execution_context=execution_context,
                    trace_sink=self._trace_sink,
                    trace_context=trace_context,
                    trace_provider=self._trace_provider,
                    trace_model=self._model,
                    trace_clock=self._clock if self._trace_sink is not None else None,
                    trace_utc_clock=(
                        self._trace_utc_clock
                        if self._trace_sink is not None
                        else None
                    ),
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
                    usage=usage.result(),
                )
            else:
                if execution_context.cancelled:
                    result = TurnResult(
                        status="cancelled",
                        session_id=self._session_id,
                        run_id=self._run_id,
                        turn_id=turn_id,
                        error="task cancelled",
                        usage=usage.result(),
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
                        usage=usage.result(),
                    )
                else:
                    result = TurnResult(
                        status="success",
                        session_id=self._session_id,
                        run_id=self._run_id,
                        turn_id=turn_id,
                        content=response,
                        usage=usage.result(),
                    )
            ended_at = self._clock()
            emit_trace(
                self._trace_sink,
                started_at=started_at,
                ended_at=ended_at,
                operation="turn",
                outcome=result.status,
                context=trace_context,
                utc_clock=self._trace_utc_clock or _utc_now,
            )
            self._emit(
                TurnFinishedEvent(
                    session_id=self._session_id,
                    run_id=self._run_id,
                    turn_id=turn_id,
                    result=result,
                    duration=ended_at - started_at,
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
        started_at = (
            self._clock() if self._trace_sink is not None else None
        )
        try:
            self.session_store.append(self._session_id, message)
        except Exception:
            if started_at is not None:
                emit_trace(
                    self._trace_sink,
                    started_at=started_at,
                    ended_at=self._clock(),
                    operation="persistence.append",
                    outcome="error",
                    context=TraceContext(
                        session_id=self._session_id,
                        run_id=self._run_id,
                        turn_id=turn_id,
                    ),
                    utc_clock=self._trace_utc_clock or _utc_now,
                )
            raise
        if started_at is not None:
            emit_trace(
                self._trace_sink,
                started_at=started_at,
                ended_at=self._clock(),
                operation="persistence.append",
                outcome="success",
                context=TraceContext(
                    session_id=self._session_id,
                    run_id=self._run_id,
                    turn_id=turn_id,
                ),
                utc_clock=self._trace_utc_clock or _utc_now,
            )
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


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
