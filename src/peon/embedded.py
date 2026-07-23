"""Embedded API for calling the agent loop without a terminal host."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
import queue
import threading
import time
from typing import Any, TypeAlias
from uuid import uuid4

from peon.agent import (
    AgentContext,
    AgentMessage,
    ModelProvider,
    ModelStreamChunk,
    ToolCall,
    ToolExecutor,
)
from peon.app.coding_session import (
    MessageEvent,
    RunLimits,
    SessionEvent,
    StopReason,
    StreamDeltaEvent,
    ToolFinishedEvent,
    ToolOutputEvent,
    ToolStartedEvent,
    TurnFinishedEvent,
    TurnResult,
    TurnStartedEvent,
)
from peon.app.observability import serialize_event
from peon.app.resources import ResourceInventory
from peon.app.session_controller import PromptIntent, SessionController
from peon.app.sessions import MemorySessionStore, SessionStore

SessionEventHandler: TypeAlias = Callable[[SessionEvent], None]


class HistoryValidationError(ValueError):
    """Raised when caller-supplied history fails validation before provider request."""


def _validate_one_message(raw: object, index: int) -> AgentMessage:
    """Validate a single raw dict or AgentMessage and return a typed AgentMessage."""
    if isinstance(raw, AgentMessage):
        return raw
    if not isinstance(raw, Mapping):
        raise HistoryValidationError(
            f"message[{index}] must be a dict or AgentMessage, got {type(raw).__name__}"
        )
    role = raw.get("role")
    if role not in {"system", "developer", "user", "assistant", "tool"}:
        raise HistoryValidationError(
            f"message[{index}] has unknown role {role!r}; "
            "expected system, developer, user, assistant, or tool"
        )
    content = raw.get("content")
    if content is None:
        raise HistoryValidationError(f"message[{index}] is missing required field 'content'")
    if not isinstance(content, str):
        raise HistoryValidationError(
            f"message[{index}] 'content' must be a string, got {type(content).__name__}"
        )
    thinking = raw.get("thinking")
    if thinking is not None and not isinstance(thinking, str):
        raise HistoryValidationError(
            f"message[{index}] 'thinking' must be a string, got {type(thinking).__name__}"
        )
    raw_tool_call = raw.get("tool_call")
    tool_call: ToolCall | None = None
    if raw_tool_call is not None:
        if not isinstance(raw_tool_call, Mapping):
            raise HistoryValidationError(
                f"message[{index}] 'tool_call' must be an object"
            )
        tc_name = raw_tool_call.get("name")
        tc_args = raw_tool_call.get("arguments")
        tc_call_id = raw_tool_call.get("call_id")
        if not isinstance(tc_name, str) or not tc_name:
            raise HistoryValidationError(
                f"message[{index}] tool call has an invalid or empty 'name'"
            )
        if not isinstance(tc_args, Mapping):
            raise HistoryValidationError(
                f"message[{index}] tool call 'arguments' must be a JSON object"
            )
        if tc_call_id is not None and not isinstance(tc_call_id, str):
            raise HistoryValidationError(
                f"message[{index}] tool call 'call_id' must be a string"
            )
        tool_call = ToolCall(name=tc_name, arguments=dict(tc_args), call_id=tc_call_id)
    tool_call_id = raw.get("tool_call_id")
    if tool_call_id is not None and not isinstance(tool_call_id, str):
        raise HistoryValidationError(
            f"message[{index}] 'tool_call_id' must be a string"
        )
    return AgentMessage(
        role=role,  # type: ignore[arg-type]
        content=content,
        thinking=thinking,
        tool_call=tool_call,
        tool_call_id=tool_call_id,
    )


def validate_history(
    messages: Sequence[AgentMessage | Mapping[str, object]],
) -> tuple[AgentMessage, ...]:
    """Validate a sequence of typed or dict messages and return typed tuple.

    Raises :exc:`HistoryValidationError` with an actionable message if any
    entry has an unknown role, invalid field type, malformed tool call, or
    missing content.  Does not raise for empty sequences.
    """
    if not isinstance(messages, Sequence) or isinstance(messages, (str, bytes)):
        raise HistoryValidationError(
            "history must be a sequence of AgentMessage or dict, "
            f"got {type(messages).__name__}"
        )
    result: list[AgentMessage] = []
    for index, raw in enumerate(messages):
        result.append(_validate_one_message(raw, index))
    return tuple(result)


# ---------------------------------------------------------------------------
# Internal queue sentinel and queue class
# ---------------------------------------------------------------------------

class _DoneSentinel:
    """Unique object that marks the end of a completed run on the event queue."""
    __slots__ = ()

    def __repr__(self) -> str:
        return "<DONE>"


_DONE = _DoneSentinel()


class BoundedEventQueue:
    """Bounded, thread-safe queue with explicit completion sentinel.

    Overflow policy:
    - Delta events (StreamDeltaEvent) are dropped silently under backpressure
      to prevent blocking the producer.
    - All other events (canonical messages, tool finish, error, cancellation,
      turn finish) are enqueued blocking — they must not be lost.
    - Completion is signalled by a distinct _DONE sentinel, never by None.
    - get() returns None only on timeout (queue is empty); it never conflates
      timeout with completion.
    """

    def __init__(self, maxsize: int = 100) -> None:
        if maxsize <= 0:
            raise ValueError(
                f"maxsize must be a positive integer, got {maxsize!r}"
            )
        self.maxsize = maxsize
        self._queue: queue.Queue[SessionEvent | _DoneSentinel] = queue.Queue(
            maxsize=maxsize
        )
        self._done_event = threading.Event()

    def put(self, event: SessionEvent | _DoneSentinel) -> None:
        """Enqueue an event or the done sentinel.

        Delta events are dropped silently when the queue is full.  All other
        events block until space is available.
        """
        if isinstance(event, _DoneSentinel):
            # Always deliver the done sentinel; enqueue blocking and signal.
            self._queue.put(event)
            self._done_event.set()
            return
        if isinstance(event, StreamDeltaEvent):
            # Deltas may be dropped under backpressure.
            try:
                self._queue.put_nowait(event)
            except queue.Full:
                pass  # delta dropped intentionally
        else:
            # Canonical events must not be lost; block until space is available.
            self._queue.put(event)

    def get(self, timeout: float | None = None) -> SessionEvent | _DoneSentinel | None:
        """Get the next item from the queue.

        Returns:
            A ``SessionEvent`` if one is available.
            The ``_DONE`` sentinel when the run is complete.
            ``None`` on timeout (queue is empty; run is still in progress).
        """
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def wait_for_done(self, timeout: float | None = None) -> bool:
        """Block until the done sentinel has been placed on the queue."""
        return self._done_event.wait(timeout=timeout)


# ---------------------------------------------------------------------------
# Typed iterator wrappers
# ---------------------------------------------------------------------------


@dataclass
class SyncEventIterator:
    """Wraps a generator so the caller can access the final TurnFinishedEvent."""

    _gen: Iterator[SessionEvent | dict[str, object]]
    _result: TurnFinishedEvent | None = field(default=None, init=False)

    def __iter__(self) -> Iterator[SessionEvent | dict[str, object]]:
        for event in self._gen:
            if isinstance(event, TurnFinishedEvent):
                self._result = event
            yield event

    @property
    def result(self) -> TurnFinishedEvent | None:
        """The final TurnFinishedEvent, or None if iteration is not yet complete."""
        return self._result


class AsyncEventIterator:
    """Wraps an async generator so the caller can access the final TurnFinishedEvent."""

    def __init__(self, gen: AsyncIterator[SessionEvent | dict[str, object]]) -> None:
        self._gen = gen
        self._result: TurnFinishedEvent | None = None

    def __aiter__(self) -> AsyncEventIterator:
        return self

    async def __anext__(self) -> SessionEvent | dict[str, object]:
        event = await self._gen.__anext__()
        if isinstance(event, TurnFinishedEvent):
            self._result = event
        return event

    @property
    def result(self) -> TurnFinishedEvent | None:
        """The final TurnFinishedEvent, or None if iteration is not yet complete."""
        return self._result


# ---------------------------------------------------------------------------
# EmbeddedSession
# ---------------------------------------------------------------------------


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
        limits: RunLimits | None = None,
    ) -> None:
        active_store = session_store or MemorySessionStore()
        active_session_id = session_id
        if active_session_id is None:
            active_session_id = active_store.create().session_id
        self._controller = SessionController(
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
            limits=limits,
        )

    @property
    def session_id(self) -> str:
        return self._controller.session_id

    @property
    def run_id(self) -> str:
        return self._controller.run_id

    @property
    def messages(self) -> tuple[AgentMessage, ...]:
        return self._controller.messages

    def load_history(
        self,
        messages: Sequence[AgentMessage | Mapping[str, object]],
    ) -> None:
        """Validate and inject history into the conversation context.

        Accepts typed ``AgentMessage`` objects or serialized dictionaries.
        Raises :exc:`HistoryValidationError` with an actionable message if
        validation fails; the conversation context is not mutated on failure.
        """
        validated = validate_history(messages)  # raises before any mutation
        for message in validated:
            self._controller._context.add(message)

    def submit(self, text: str) -> TurnResult:
        """Submit one text prompt and return its structured turn result."""
        return self._controller.dispatch(PromptIntent(text))

    def cancel(self) -> bool:
        """Request cancellation of the active prompt, if one is running."""
        return self._controller.cancel()

    def iter_events(
        self,
        text: str,
        *,
        max_buffer_size: int = 100,
        schema_version: int | None = None,
    ) -> SyncEventIterator:
        """Submit text prompt and yield live events synchronously.

        Args:
            text: The prompt to submit.
            max_buffer_size: Positive integer capacity for the internal buffer.
            schema_version: When set to 1 or 2, yields serialized dicts
                using that schema instead of typed events.

        Returns:
            A :class:`SyncEventIterator` whose ``.result`` property exposes
            the final :class:`TurnFinishedEvent` after iteration completes.
        """
        return SyncEventIterator(
            self._iter_events_gen(
                text,
                max_buffer_size=max_buffer_size,
                schema_version=schema_version,
            )
        )

    def _iter_events_gen(
        self,
        text: str,
        *,
        max_buffer_size: int,
        schema_version: int | None,
    ) -> Iterator[SessionEvent | dict[str, object]]:
        event_queue = BoundedEventQueue(maxsize=max_buffer_size)

        def _on_event(event: SessionEvent) -> None:
            event_queue.put(event)

        sub_session = EmbeddedSession(
            provider=self._controller.provider,
            session_store=self._controller.session_store,
            session_id=self.session_id,
            run_id=self.run_id,
            context=self._controller._context,
            tools=self._controller._executor,
            model=self._controller._model,
            resources=self._controller._resources,
            on_event=_on_event,
            limits=self._controller._limits,
        )

        def _worker() -> None:
            try:
                sub_session.submit(text)
            finally:
                event_queue.put(_DONE)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

        try:
            while True:
                item = event_queue.get(timeout=0.1)
                if isinstance(item, _DoneSentinel):
                    # Drain any remaining items already in the queue
                    while True:
                        remaining = event_queue.get(timeout=0.0)
                        if remaining is None or isinstance(remaining, _DoneSentinel):
                            break
                        yield _maybe_serialize(remaining, schema_version)
                    break
                if item is not None:
                    yield _maybe_serialize(item, schema_version)
        finally:
            sub_session.cancel()
            thread.join(timeout=2.0)

    def aiter_events(
        self,
        text: str,
        *,
        max_buffer_size: int = 100,
        schema_version: int | None = None,
    ) -> AsyncEventIterator:
        """Submit text prompt and yield live events asynchronously.

        Args:
            text: The prompt to submit.
            max_buffer_size: Positive integer capacity for the internal buffer.
            schema_version: When set to 1 or 2, yields serialized dicts
                using that schema instead of typed events.

        Returns:
            An :class:`AsyncEventIterator` whose ``.result`` property exposes
            the final :class:`TurnFinishedEvent` after iteration completes.
        """
        return AsyncEventIterator(
            self._aiter_events_gen(
                text,
                max_buffer_size=max_buffer_size,
                schema_version=schema_version,
            )
        )

    async def _aiter_events_gen(
        self,
        text: str,
        *,
        max_buffer_size: int,
        schema_version: int | None,
    ) -> AsyncIterator[SessionEvent | dict[str, object]]:
        loop = asyncio.get_running_loop()
        event_queue = BoundedEventQueue(maxsize=max_buffer_size)

        def _on_event(event: SessionEvent) -> None:
            event_queue.put(event)

        sub_session = EmbeddedSession(
            provider=self._controller.provider,
            session_store=self._controller.session_store,
            session_id=self.session_id,
            run_id=self.run_id,
            context=self._controller._context,
            tools=self._controller._executor,
            model=self._controller._model,
            resources=self._controller._resources,
            on_event=_on_event,
            limits=self._controller._limits,
        )

        def _worker() -> None:
            try:
                sub_session.submit(text)
            finally:
                event_queue.put(_DONE)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

        try:
            while True:
                # Blocking get on the thread-pool executor: returns as soon as
                # any item (event or _DONE sentinel) becomes available.  This
                # prevents the 50 ms poll race that terminated async iteration
                # before all events from a slow provider arrived.
                item = await loop.run_in_executor(None, event_queue.get)
                if isinstance(item, _DoneSentinel):
                    # Drain any remaining events that already arrived before
                    # the sentinel was consumed.
                    while True:
                        remaining = event_queue.get(timeout=0.0)
                        if remaining is None or isinstance(remaining, _DoneSentinel):
                            break
                        yield _maybe_serialize(remaining, schema_version)
                    break
                if item is not None:
                    yield _maybe_serialize(item, schema_version)
        except asyncio.CancelledError:
            sub_session.cancel()
            raise
        finally:
            sub_session.cancel()
            await loop.run_in_executor(None, thread.join, 2.0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _maybe_serialize(
    event: SessionEvent,
    schema_version: int | None,
) -> SessionEvent | dict[str, object]:
    """Return the event as-is or serialized if schema_version is set."""
    if schema_version is None:
        return event
    return serialize_event(event, schema_version=schema_version)


__all__ = [
    "AsyncEventIterator",
    "BoundedEventQueue",
    "EmbeddedSession",
    "HistoryValidationError",
    "MessageEvent",
    "SessionEvent",
    "StreamDeltaEvent",
    "SyncEventIterator",
    "ToolFinishedEvent",
    "ToolOutputEvent",
    "ToolStartedEvent",
    "TurnFinishedEvent",
    "TurnResult",
    "TurnStartedEvent",
    "validate_history",
]