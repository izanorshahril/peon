"""Host-neutral coding-session behavior."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import logging
from threading import Lock
import time
from typing import Any, ClassVar, Literal, TypeAlias
from uuid import uuid4

from peon.agent import (
    AgentContext,
    AgentError,
    AgentMessage,
    LimitExceededError,
    ModelProvider,
    ModelStreamChunk,
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
from .sessions import SessionStore

StopReason: TypeAlias = Literal[
    "completed",
    "cancelled",
    "max_provider_calls_exceeded",
    "max_tool_calls_exceeded",
    "max_elapsed_seconds_exceeded",
    "max_input_tokens_exceeded",
    "max_output_tokens_exceeded",
    "max_total_tokens_exceeded",
    "max_cost_exceeded",
    "provider_error",
    "tool_error",
    "persistence_error",
    "consumer_error",
    "internal_error",
]


@dataclass(frozen=True, slots=True)
class RunLimits:
    """Immutable run policy bounds for automation and hosted execution."""

    max_provider_calls: int | None = None
    max_tool_calls: int | None = None
    max_elapsed_seconds: float | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_total_tokens: int | None = None
    max_cost: float | None = None
    currency: str | None = None


TurnStatus = Literal["success", "error", "cancelled"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class TurnResult:
    status: TurnStatus
    session_id: str
    run_id: str
    turn_id: str
    content: str | None = None
    error: str | None = None
    usage: Usage | None = None
    stop_reason: StopReason | str | None = None

    def __post_init__(self) -> None:
        if self.stop_reason is None:
            default_reason = (
                "completed"
                if self.status == "success"
                else "cancelled"
                if self.status == "cancelled"
                else "provider_error"
            )
            object.__setattr__(self, "stop_reason", default_reason)


@dataclass(frozen=True, slots=True)
class TurnStartedEvent:
    event_type: ClassVar[str] = "turn_started"
    session_id: str
    run_id: str
    turn_id: str
    started_at: float
    schema_version: int = 2
    timestamp: datetime = field(default_factory=_utc_now)
    sequence: int = 0
    message_id: str | None = None
    operation_id: str | None = None
    provider_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class MessageEvent:
    event_type: ClassVar[str] = "message"
    session_id: str
    run_id: str
    turn_id: str
    message: AgentMessage
    schema_version: int = 2
    timestamp: datetime = field(default_factory=_utc_now)
    sequence: int = 0
    message_id: str | None = None
    operation_id: str | None = None
    provider_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class StreamDeltaEvent:
    event_type: ClassVar[str] = "stream_delta"
    session_id: str
    run_id: str
    turn_id: str
    chunk: ModelStreamChunk
    schema_version: int = 2
    timestamp: datetime = field(default_factory=_utc_now)
    sequence: int = 0
    message_id: str | None = None
    operation_id: str | None = None
    provider_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class TurnFinishedEvent:
    event_type: ClassVar[str] = "turn_finished"
    session_id: str
    run_id: str
    turn_id: str
    result: TurnResult
    duration: float
    schema_version: int = 2
    timestamp: datetime = field(default_factory=_utc_now)
    sequence: int = 0
    message_id: str | None = None
    operation_id: str | None = None
    provider_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class CommandOutcomeEvent:
    event_type: ClassVar[str] = "command_outcome"
    session_id: str
    run_id: str
    command: str
    status: str
    output: str | None = None
    turn_id: str | None = None
    schema_version: int = 2
    timestamp: datetime = field(default_factory=_utc_now)
    sequence: int = 0
    message_id: str | None = None
    operation_id: str | None = None
    provider_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class SelectionRequestEvent:
    event_type: ClassVar[str] = "selection_request"
    session_id: str
    run_id: str
    prompt: str
    options: tuple[Mapping[str, object], ...]
    turn_id: str | None = None
    schema_version: int = 2
    timestamp: datetime = field(default_factory=_utc_now)
    sequence: int = 0
    message_id: str | None = None
    operation_id: str | None = None
    provider_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class CancellationEvent:
    event_type: ClassVar[str] = "cancellation"
    session_id: str
    run_id: str
    reason: str
    turn_id: str | None = None
    schema_version: int = 2
    timestamp: datetime = field(default_factory=_utc_now)
    sequence: int = 0
    message_id: str | None = None
    operation_id: str | None = None
    provider_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class TerminalErrorEvent:
    event_type: ClassVar[str] = "terminal_error"
    session_id: str
    run_id: str
    error: str
    stop_reason: StopReason | str
    turn_id: str | None = None
    schema_version: int = 2
    timestamp: datetime = field(default_factory=_utc_now)
    sequence: int = 0
    message_id: str | None = None
    operation_id: str | None = None
    provider_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class ToolStartedEvent:
    event_type: ClassVar[str] = "tool_started"
    session_id: str
    run_id: str
    operation_id: str
    tool_name: str
    arguments: Mapping[str, object]
    turn_id: str | None = None
    call_id: str | None = None
    source: Literal["model", "shell"] = "model"
    schema_version: int = 2
    timestamp: datetime = field(default_factory=_utc_now)
    sequence: int = 0
    message_id: str | None = None
    provider_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class ToolOutputEvent:
    event_type: ClassVar[str] = "tool_output"
    session_id: str
    run_id: str
    operation_id: str
    stream: str
    chunk: str
    turn_id: str | None = None
    schema_version: int = 2
    timestamp: datetime = field(default_factory=_utc_now)
    sequence: int = 0
    message_id: str | None = None
    provider_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class ToolFinishedEvent:
    event_type: ClassVar[str] = "tool_finished"
    session_id: str
    run_id: str
    operation_id: str
    tool_name: str
    outcome: Literal["success", "error", "cancelled"]
    turn_id: str | None = None
    result: str | None = None
    error: str | None = None
    call_id: str | None = None
    source: Literal["model", "shell"] = "model"
    schema_version: int = 2
    timestamp: datetime = field(default_factory=_utc_now)
    sequence: int = 0
    message_id: str | None = None
    provider_call_id: str | None = None


SessionEvent: TypeAlias = (
    TurnStartedEvent
    | MessageEvent
    | StreamDeltaEvent
    | TurnFinishedEvent
    | CommandOutcomeEvent
    | SelectionRequestEvent
    | CancellationEvent
    | TerminalErrorEvent
    | ToolStartedEvent
    | ToolOutputEvent
    | ToolFinishedEvent
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
        event_utc_clock: Callable[[], datetime] = _utc_now,
        event_sequence_start: int = 0,
        limits: RunLimits | None = None,
        journal_sink: Any | None = None,
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
        self._event_utc_clock = event_utc_clock
        self._limits = limits
        self._journal_sink = journal_sink
        self._active_execution_context: ToolExecutionContext | None = None
        (
            self._persisted_message_count,
            self._load_error,
        ) = self._stored_message_count()
        self._persistence_error: str | None = None
        self._state_lock = Lock()
        self._active_on_event: EventHandler | None = None
        if event_sequence_start < 0:
            raise ValueError("event_sequence_start must be non-negative")
        self._event_sequence = event_sequence_start
        self._active_message_id: str | None = None

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
        on_event: EventHandler | None = None,
    ) -> TurnResult:
        """Run one prompt and return a structured terminal outcome."""
        turn_id = self._id_factory()
        active_op_id: str | None = None
        active_tool_call: ToolCall | None = None

        def _handle_tool_output(stream_name: str, chunk: str) -> None:
            op_id = active_op_id or turn_id
            self._emit(
                ToolOutputEvent(
                    session_id=self._session_id,
                    run_id=self._run_id,
                    turn_id=turn_id,
                    operation_id=op_id,
                    stream=stream_name,
                    chunk=chunk,
                )
            )
            if self._on_tool_output is not None:
                self._on_tool_output(stream_name, chunk)

        execution_context = ToolExecutionContext(on_output=_handle_tool_output)
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
            self._active_on_event = on_event

        def _handle_on_message(message: AgentMessage) -> None:
            nonlocal active_op_id, active_tool_call
            if message.role == "assistant" and message.tool_call is not None:
                op_id = self._id_factory()
                active_op_id = op_id
                active_tool_call = message.tool_call
                self._emit(
                    ToolStartedEvent(
                        session_id=self._session_id,
                        run_id=self._run_id,
                        turn_id=turn_id,
                        operation_id=op_id,
                        tool_name=message.tool_call.name,
                        arguments=message.tool_call.arguments,
                        call_id=message.tool_call.call_id,
                        source="model",
                    )
                )
            elif message.role == "tool":
                op_id = active_op_id or self._id_factory()
                tool_name = (
                    active_tool_call.name
                    if active_tool_call is not None
                    else "unknown"
                )
                call_id = (
                    active_tool_call.call_id
                    if active_tool_call is not None
                    else message.tool_call_id
                )
                outcome: Literal["success", "error", "cancelled"]
                if execution_context.cancelled:
                    outcome = "cancelled"
                elif message.content.startswith("tool error:"):
                    outcome = "error"
                else:
                    outcome = "success"

                self._emit(
                    ToolFinishedEvent(
                        session_id=self._session_id,
                        run_id=self._run_id,
                        turn_id=turn_id,
                        operation_id=op_id,
                        tool_name=tool_name,
                        outcome=outcome,
                        result=message.content if outcome == "success" else None,
                        error=message.content if outcome != "success" else None,
                        call_id=call_id,
                        source="model",
                    )
                )
                active_op_id = None
                active_tool_call = None

            self._persist_message(message, turn_id)

        started_at = self._clock()
        self._active_message_id = None
        usage = _UsageAccumulator()
        self._persistence_error = self._load_error
        self._flush_pending_messages(turn_id)
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
                    on_message=_handle_on_message,
                    on_usage=usage.add,
                    on_stream_chunk=lambda chunk: self._emit(
                        StreamDeltaEvent(
                            session_id=self._session_id,
                            run_id=self._run_id,
                            turn_id=turn_id,
                            chunk=chunk,
                        )
                    ),
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
                    limits=self._limits,
                )
            except LimitExceededError as error:
                result = TurnResult(
                    status="error",
                    session_id=self._session_id,
                    run_id=self._run_id,
                    turn_id=turn_id,
                    error=str(error),
                    usage=usage.result(),
                    stop_reason=error.stop_reason,
                )
                self._emit(
                    TerminalErrorEvent(
                        session_id=self._session_id,
                        run_id=self._run_id,
                        turn_id=turn_id,
                        error=result.error or "task failed",
                        stop_reason=result.stop_reason or "internal_error",
                    )
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
                if execution_context.cancelled:
                    self._emit(
                        CancellationEvent(
                            session_id=self._session_id,
                            run_id=self._run_id,
                            turn_id=turn_id,
                            reason=result.error or "task cancelled",
                        )
                    )
                else:
                    self._emit(
                        TerminalErrorEvent(
                            session_id=self._session_id,
                            run_id=self._run_id,
                            turn_id=turn_id,
                            error=result.error or "task failed",
                            stop_reason=result.stop_reason or "provider_error",
                        )
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
                    self._emit(
                        CancellationEvent(
                            session_id=self._session_id,
                            run_id=self._run_id,
                            turn_id=turn_id,
                            reason="task cancelled",
                        )
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
            if self._persistence_error is not None:
                persistence_error = self._persistence_error
                result_error = result.error
                if result_error is not None and result_error != persistence_error:
                    persistence_error = f"{result_error}; persistence failed: {persistence_error}"
                result = TurnResult(
                    status="error",
                    session_id=result.session_id,
                    run_id=result.run_id,
                    turn_id=result.turn_id,
                    error=persistence_error,
                    usage=result.usage,
                )
                self._emit(
                    TerminalErrorEvent(
                        session_id=self._session_id,
                        run_id=self._run_id,
                        turn_id=turn_id,
                        error=persistence_error,
                        stop_reason="persistence_error",
                    )
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
                self._active_on_event = None
            self._active_message_id = None


    def cancel(self) -> bool:
        """Request cancellation of the active provider/tool turn."""
        with self._state_lock:
            execution_context = self._active_execution_context
        if execution_context is None:
            return False
        execution_context.cancel()
        return True

    def _persist_message(self, message: AgentMessage, turn_id: str) -> None:
        if self._persistence_error is not None:
            return
        messages = conversation_messages_without_resource_prompt(
            self._context.messages,
            self._resources,
        )
        message_index = len(messages) - 1
        if message_index != self._persisted_message_count:
            self._persistence_error = (
                "conversation context does not match persisted session"
            )
            return
        if not self._append_message(message, turn_id):
            return
        self._emit_message(message, turn_id)

    def _emit_message(self, message: AgentMessage, turn_id: str) -> None:
        self._emit(
            MessageEvent(
                session_id=self._session_id,
                run_id=self._run_id,
                turn_id=turn_id,
                message=message,
            )
        )

    def _flush_pending_messages(self, turn_id: str) -> None:
        messages = conversation_messages_without_resource_prompt(
            self._context.messages,
            self._resources,
        )
        if self._persisted_message_count > len(messages):
            self._persistence_error = (
                "conversation context does not match persisted session"
            )
            return
        while self._persisted_message_count < len(messages):
            message = messages[self._persisted_message_count]
            if not self._append_message(message, turn_id):
                return

    def _append_message(self, message: AgentMessage, turn_id: str) -> bool:
        started_at = self._clock() if self._trace_sink is not None else None
        try:
            self.session_store.append(self._session_id, message)
        except Exception as error:
            self._persistence_error = str(error)
            outcome = "error"
        else:
            self._persisted_message_count += 1
            outcome = "success"
        if started_at is not None:
            emit_trace(
                self._trace_sink,
                started_at=started_at,
                ended_at=self._clock(),
                operation="persistence.append",
                outcome=outcome,
                context=TraceContext(
                    session_id=self._session_id,
                    run_id=self._run_id,
                    turn_id=turn_id,
                ),
                utc_clock=self._trace_utc_clock or _utc_now,
            )
        return outcome == "success"

    def _stored_message_count(self) -> tuple[int, str | None]:
        try:
            return len(self.session_store.load(self._session_id).messages), None
        except Exception as error:
            return 0, str(error)

    def _emit(self, event: SessionEvent) -> None:
        message_id = event.message_id
        if isinstance(event, StreamDeltaEvent):
            if self._active_message_id is None:
                self._active_message_id = uuid4().hex
            message_id = self._active_message_id
        elif isinstance(event, MessageEvent):
            if event.message.role == "assistant" and event.message.tool_call is None:
                if self._active_message_id is None:
                    self._active_message_id = uuid4().hex
                message_id = self._active_message_id
            elif message_id is None:
                message_id = uuid4().hex
        event = replace(
            event,
            schema_version=2,
            timestamp=self._event_utc_clock(),
            sequence=self._event_sequence,
            message_id=message_id,
        )
        self._event_sequence += 1
        if self._journal_sink is not None:
            try:
                self._journal_sink.write_event(event)
            except Exception:
                if getattr(self._journal_sink, "strict", False):
                    raise
                logger.exception("event journal sink failed")
        if self._on_event is not None:
            try:
                self._on_event(event)
            except Exception:
                logger.exception("coding session event handler failed")
        if self._active_on_event is not None:
            try:
                self._active_on_event(event)
            except Exception:
                logger.exception("turn event handler failed")
