from collections.abc import Sequence
import asyncio
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import cast

import pytest

from peon.agent import AgentMessage, ModelResponse, ToolCall, ToolDefinition
from peon.app.coding_session import (
    MessageEvent,
    TurnFinishedEvent,
    TurnStartedEvent,
)
from peon.app.sessions import MemorySessionStore
from peon.embedded import (
    BoundedEventQueue,
    EmbeddedSession,
    HistoryValidationError,
    validate_history,
)
from peon.app.resources import ResourceInventory
from peon.extensions import ExtensionRegistry


class FakeProvider:
    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        return ModelResponse(content="embedded response")


class BlockingProvider:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        self.started.set()
        self.release.wait(timeout=2)
        return ModelResponse(content="finished")


class DelayedProvider:
    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        time.sleep(0.1)
        return ModelResponse(content="finished")


class ToolProvider:
    def __init__(self) -> None:
        self.received_messages: list[tuple[AgentMessage, ...]] = []
        self.received_tools: list[tuple[ToolDefinition, ...]] = []

    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        self.received_messages.append(tuple(messages))
        self.received_tools.append(tuple(tools))
        if any(message.role == "tool" for message in messages):
            return ModelResponse(content="tool result")
        return ModelResponse(
            tool_call=ToolCall(
                name="lookup",
                arguments={"key": "owner"},
                call_id="call-1",
            )
        )


class FailingProvider:
    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        raise RuntimeError("provider unavailable")


def test_embedded_session_submits_text_and_observes_typed_events() -> None:
    store = MemorySessionStore()
    events: list[object] = []
    session = EmbeddedSession(
        provider=FakeProvider(),
        session_store=store,
        on_event=events.append,
        run_id="run-1",
        clock=iter((1.0, 1.5)).__next__,
        id_factory=lambda: "turn-1",
    )

    result = session.submit("hello")

    assert result.status == "success"
    assert result.content == "embedded response"
    assert result.session_id == session.session_id
    assert [type(event) for event in events] == [
        TurnStartedEvent,
        MessageEvent,
        MessageEvent,
        TurnFinishedEvent,
    ]
    assert store.load(session.session_id).messages[-1].content == (
        "embedded response"
    )


def test_embedded_session_cancels_active_work() -> None:
    provider = BlockingProvider()
    session = EmbeddedSession(
        provider=provider,
        session_store=MemorySessionStore(),
        id_factory=lambda: "turn-1",
    )
    result: list[object] = []
    worker = threading.Thread(
        target=lambda: result.append(session.submit("stop this")),
    )

    worker.start()
    assert provider.started.wait(timeout=2)
    assert session.cancel() is True
    provider.release.set()
    worker.join(timeout=2)

    assert len(result) == 1
    assert cast(object, result[0]).status == "cancelled"


def test_embedded_session_forwards_resources_tools_and_persistence() -> None:
    store = MemorySessionStore()
    record = store.create()
    provider = ToolProvider()
    registry = ExtensionRegistry()
    registry.register_tool(
        name="lookup",
        description="Look up a value.",
        parameters={"type": "object"},
        handler=lambda arguments: "owner:Peon",
    )
    session = EmbeddedSession(
        provider=provider,
        session_store=store,
        session_id=record.session_id,
        resources=ResourceInventory(effective_system_prompt="Be concise."),
        tools=registry,
        clock=iter((1.0, 1.1, 1.2, 1.3, 1.4, 1.5)).__next__,
        id_factory=lambda: "turn-1",
    )

    result = session.submit("look up the owner")

    assert result.status == "success"
    assert result.content == "tool result"
    assert provider.received_tools == [registry.tools, registry.tools]
    assert provider.received_messages[0] == (
        AgentMessage(role="system", content="Be concise."),
        AgentMessage(role="user", content="look up the owner"),
    )
    assert store.load(record.session_id).messages == (
        AgentMessage(role="user", content="look up the owner"),
        AgentMessage(
            role="assistant",
            content="",
            tool_call=ToolCall(
                name="lookup",
                arguments={"key": "owner"},
                call_id="call-1",
            ),
        ),
        AgentMessage(
            role="tool",
            content="owner:Peon",
            tool_call_id="call-1",
        ),
        AgentMessage(role="assistant", content="tool result"),
    )


def test_embedded_session_returns_provider_failure_as_structured_result() -> None:
    store = MemorySessionStore()
    record = store.create()
    session = EmbeddedSession(
        provider=FailingProvider(),
        session_store=store,
        session_id=record.session_id,
        run_id="run-1",
        id_factory=lambda: "turn-1",
    )

    result = session.submit("fail this request")

    assert result.status == "error"
    assert result.run_id == "run-1"
    assert result.error == "provider request failed: provider unavailable"
    assert store.load(record.session_id).messages == (
        AgentMessage(role="user", content="fail this request"),
    )


def test_embedded_import_does_not_load_terminal_frontends() -> None:
    script = """
import sys
from peon.embedded import EmbeddedSession

assert "textual" not in sys.modules
assert "peon.app.textual_tui" not in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_embedded_session_sync_and_async_event_iterators() -> None:
    session = EmbeddedSession(
        provider=FakeProvider(),
        session_store=MemorySessionStore(),
    )

    sync_events = list(session.iter_events("hello"))
    assert len(sync_events) >= 2
    assert isinstance(sync_events[0], TurnStartedEvent)
    assert isinstance(sync_events[-1], TurnFinishedEvent)

    async def _exercise_async() -> None:
        async_events: list[object] = []
        async for event in session.aiter_events("world"):
            async_events.append(event)
        assert len(async_events) >= 2
        assert isinstance(async_events[0], TurnStartedEvent)
        assert isinstance(async_events[-1], TurnFinishedEvent)

    asyncio.run(_exercise_async())


def test_embedded_async_iterator_waits_for_delayed_terminal_event() -> None:
    """Slow provider must not terminate async iteration early via polling timeout."""
    session = EmbeddedSession(
        provider=DelayedProvider(),
        session_store=MemorySessionStore(),
    )

    async def _collect_events() -> list[object]:
        return [event async for event in session.aiter_events("wait")]

    events = asyncio.run(_collect_events())

    assert isinstance(events[-1], TurnFinishedEvent)


@pytest.mark.xfail(
    strict=True,
    reason="0.3.1 ticket 04: tool lifecycle is not in session event stream",
)
def test_embedded_tool_run_emits_tool_start_and_finish_events() -> None:
    events: list[object] = []
    registry = ExtensionRegistry()
    registry.register_tool(
        name="lookup",
        description="Look up a value.",
        parameters={"type": "object"},
        handler=lambda arguments: "owner:Peon",
    )
    session = EmbeddedSession(
        provider=ToolProvider(),
        session_store=MemorySessionStore(),
        tools=registry,
        on_event=events.append,
    )

    result = session.submit("look up the owner")
    event_names = [type(event).__name__ for event in events]

    assert result.status == "success"
    assert "ToolStartedEvent" in event_names
    assert "ToolFinishedEvent" in event_names


# ---------------------------------------------------------------------------
# Ticket 03 focused tests
# ---------------------------------------------------------------------------


# --- BoundedEventQueue ---

def test_bounded_event_queue_rejects_non_positive_maxsize() -> None:
    """Buffer size must be a positive integer."""
    with pytest.raises(ValueError, match="maxsize"):
        BoundedEventQueue(maxsize=0)
    with pytest.raises(ValueError, match="maxsize"):
        BoundedEventQueue(maxsize=-1)


def test_bounded_event_queue_done_sentinel_distinct_from_empty_poll() -> None:
    """Empty queue timeout must not look like completion; done signal is explicit."""
    from peon.embedded import _DONE  # type: ignore[attr-defined]
    q = BoundedEventQueue(maxsize=10)
    # An empty-queue poll with a short timeout returns None (queue empty)
    result = q.get(timeout=0.01)
    assert result is None, "empty poll must return None, not the done sentinel"
    # Placing the sentinel and getting it returns the sentinel, not None
    q.put(_DONE)
    sentinel_result = q.get(timeout=0.1)
    assert sentinel_result is _DONE, "done sentinel must be distinguishable from None"


# --- validate_history ---

def test_validate_history_accepts_typed_messages() -> None:
    messages = [
        AgentMessage(role="user", content="hello"),
        AgentMessage(role="assistant", content="hi"),
    ]
    result = validate_history(messages)
    assert result == tuple(messages)


def test_validate_history_accepts_dict_messages() -> None:
    raw = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    result = validate_history(raw)
    assert result[0] == AgentMessage(role="user", content="hello")
    assert result[1] == AgentMessage(role="assistant", content="hi")


def test_validate_history_accepts_tool_calls_and_results() -> None:
    raw = [
        {"role": "user", "content": "do a tool call"},
        {
            "role": "assistant",
            "content": "",
            "tool_call": {"name": "lookup", "arguments": {}, "call_id": "c1"},
        },
        {"role": "tool", "content": "result", "tool_call_id": "c1"},
        {"role": "assistant", "content": "done"},
    ]
    result = validate_history(raw)
    assert len(result) == 4
    assert result[1].tool_call is not None
    assert result[1].tool_call.name == "lookup"
    assert result[2].role == "tool"


def test_validate_history_accepts_thinking_field() -> None:
    raw = [
        {"role": "assistant", "content": "answer", "thinking": "let me think"},
    ]
    result = validate_history(raw)
    assert result[0].thinking == "let me think"


def test_validate_history_rejects_unknown_role() -> None:
    raw = [{"role": "admin", "content": "hi"}]
    with pytest.raises(HistoryValidationError, match="role"):
        validate_history(raw)


def test_validate_history_rejects_missing_content() -> None:
    raw = [{"role": "user"}]
    with pytest.raises(HistoryValidationError, match="content"):
        validate_history(raw)


def test_validate_history_rejects_invalid_content_type() -> None:
    raw = [{"role": "user", "content": 42}]
    with pytest.raises(HistoryValidationError, match="content"):
        validate_history(raw)


def test_validate_history_rejects_invalid_tool_call() -> None:
    raw = [
        {
            "role": "assistant",
            "content": "",
            "tool_call": {"name": "", "arguments": {}},  # empty name
        }
    ]
    with pytest.raises(HistoryValidationError, match="tool"):
        validate_history(raw)


def test_validate_history_rejects_non_mapping_message() -> None:
    raw = ["not a dict"]
    with pytest.raises(HistoryValidationError):
        validate_history(raw)


def test_validate_history_rejects_non_mapping_input() -> None:
    with pytest.raises(HistoryValidationError):
        validate_history("not a list")  # type: ignore[arg-type]


# --- EmbeddedSession.load_history ---

def test_embedded_session_load_history_accepts_typed_messages() -> None:
    """load_history injects typed AgentMessage objects into conversation context."""
    session = EmbeddedSession(
        provider=FakeProvider(),
        session_store=MemorySessionStore(),
    )
    history = [
        AgentMessage(role="user", content="previous prompt"),
        AgentMessage(role="assistant", content="previous reply"),
    ]
    session.load_history(history)
    assert len(session.messages) == 2
    assert session.messages[0].content == "previous prompt"


def test_embedded_session_load_history_accepts_dict_messages() -> None:
    """load_history validates and converts dict messages before accepting them."""
    session = EmbeddedSession(
        provider=FakeProvider(),
        session_store=MemorySessionStore(),
    )
    history = [
        {"role": "user", "content": "previous prompt"},
        {"role": "assistant", "content": "previous reply"},
    ]
    session.load_history(history)
    assert len(session.messages) == 2


def test_embedded_session_load_history_rejects_invalid_history() -> None:
    """load_history raises HistoryValidationError on invalid input before mutation."""
    session = EmbeddedSession(
        provider=FakeProvider(),
        session_store=MemorySessionStore(),
    )
    bad_history = [{"role": "unknown_role", "content": "hi"}]
    with pytest.raises(HistoryValidationError):
        session.load_history(bad_history)
    # Context must not be mutated on validation failure
    assert len(session.messages) == 0


def test_embedded_session_load_history_import_does_not_load_terminal() -> None:
    """Loading history must not trigger Textual or prompt-toolkit imports."""
    script = """
import sys
from peon.embedded import EmbeddedSession, validate_history, HistoryValidationError
assert "textual" not in sys.modules
assert "peon.app.textual_tui" not in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


# --- Dictionary event mode ---

def test_iter_events_yields_dict_events_with_schema_version_2() -> None:
    """schema_version=2 yields serialized dict events from iter_events."""
    session = EmbeddedSession(
        provider=FakeProvider(),
        session_store=MemorySessionStore(),
    )
    events = list(session.iter_events("hello", schema_version=2))
    assert len(events) >= 2
    assert all(isinstance(e, dict) for e in events)
    assert events[0]["event_type"] == "turn_started"
    assert events[-1]["event_type"] == "turn_finished"


def test_aiter_events_yields_dict_events_with_schema_version_2() -> None:
    """schema_version=2 yields serialized dict events from aiter_events."""
    session = EmbeddedSession(
        provider=FakeProvider(),
        session_store=MemorySessionStore(),
    )

    async def _collect() -> list[object]:
        return [e async for e in session.aiter_events("hello", schema_version=2)]

    events = asyncio.run(_collect())
    assert len(events) >= 2
    assert all(isinstance(e, dict) for e in events)
    assert cast(dict, events[0])["event_type"] == "turn_started"
    assert cast(dict, events[-1])["event_type"] == "turn_finished"


# --- TurnResult from iterator ---

def test_iter_events_result_exposes_turn_result() -> None:
    """Caller can get TurnResult after sync iteration without a second run."""
    session = EmbeddedSession(
        provider=FakeProvider(),
        session_store=MemorySessionStore(),
    )
    it = session.iter_events("hello")
    events = list(it)
    result = it.result
    assert isinstance(result, TurnFinishedEvent)
    assert result.result.status == "success"
    # Iteration consumed events
    assert len(events) >= 2


def test_aiter_events_result_exposes_turn_result() -> None:
    """Caller can get TurnResult after async iteration without a second run."""
    session = EmbeddedSession(
        provider=FakeProvider(),
        session_store=MemorySessionStore(),
    )

    async def _collect() -> tuple[list[object], object]:
        it = session.aiter_events("hello")
        events = [e async for e in it]
        return events, it.result

    events, result = asyncio.run(_collect())
    assert isinstance(result, TurnFinishedEvent)
    assert result.result.status == "success"
    assert len(events) >= 2


# --- Async cancellation reaches worker ---

def test_async_iterator_cancellation_reaches_active_turn() -> None:
    """CancelledError from caller propagates cancel() to the active session."""
    provider = BlockingProvider()
    session = EmbeddedSession(
        provider=provider,
        session_store=MemorySessionStore(),
    )

    async def _run_and_cancel() -> None:
        it = session.aiter_events("block")
        # Start consuming; first event triggers the worker
        task = asyncio.create_task(_drain(it))
        # Wait for the provider to start, then cancel the consumer task
        await asyncio.get_event_loop().run_in_executor(
            None, provider.started.wait, 2.0
        )
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        # Release the blocking provider so the worker can exit
        provider.release.set()

    async def _drain(it: object) -> list[object]:
        return [e async for e in it]  # type: ignore[attr-defined]

    asyncio.run(_run_and_cancel())