from collections.abc import Sequence
import subprocess
import sys
import threading
from pathlib import Path
from typing import cast

from peon.agent import AgentMessage, ModelResponse, ToolCall, ToolDefinition
from peon.app.coding_session import (
    MessageEvent,
    TurnFinishedEvent,
    TurnStartedEvent,
)
from peon.app.sessions import MemorySessionStore
from peon.embedded import EmbeddedSession
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
    import asyncio

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