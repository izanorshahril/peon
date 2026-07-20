from dataclasses import dataclass, field
from collections.abc import Sequence
from threading import Event, Thread

from peon.agent import (
    AgentMessage,
    ModelResponse,
    ToolCall,
    ToolDefinition,
    ToolExecutionContext,
    Usage,
)
from peon.app.coding_session import (
    CodingSession,
    MessageEvent,
    TurnFinishedEvent,
    TurnStartedEvent,
    TurnResult,
)
from peon.app.resources import ResourceInventory
from peon.app.sessions import MemorySessionStore
from peon.extensions import ExtensionRegistry, register_sample_tools


@dataclass
class CapturingProvider:
    received_messages: tuple[AgentMessage, ...] = ()

    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        self.received_messages = tuple(messages)
        return ModelResponse(content="Done.")


@dataclass
class FailingProvider:
    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        raise RuntimeError("provider unavailable")


@dataclass
class FailingStore(MemorySessionStore):
    def append(self, session_id: str, message: AgentMessage) -> None:
        raise RuntimeError("persistence unavailable")


@dataclass
class BlockingExecutor:
    started: Event
    definitions: tuple[ToolDefinition, ...] = ()
    wakeup: Event = field(default_factory=Event)

    @property
    def tools(self) -> tuple[ToolDefinition, ...]:
        return self.definitions

    def invoke(self, name: str, arguments: dict[str, object]) -> str:
        raise AssertionError("context-aware invocation is required")

    def invoke_with_context(
        self,
        name: str,
        arguments: dict[str, object],
        context: ToolExecutionContext,
    ) -> str:
        self.started.set()
        while not context.cancelled:
            self.wakeup.wait(0.01)
        return "cancelled"


@dataclass
class ToolProvider:
    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        if not any(message.role == "tool" for message in messages):
            return ModelResponse(
                tool_call=ToolCall(name="wait", arguments={}, call_id="call-1")
            )
        return ModelResponse(content="Finished.")


@dataclass
class UsageProvider:
    responses: list[ModelResponse]

    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        return self.responses.pop(0)


def test_coding_session_runs_turn_persists_messages_and_applies_resources() -> None:
    store = MemorySessionStore()
    record = store.create()
    provider = CapturingProvider()
    events = []
    session = CodingSession(
        provider=provider,
        session_store=store,
        session_id=record.session_id,
        resources=ResourceInventory(effective_system_prompt="Use brief answers."),
        run_id="run-1",
        on_event=events.append,
        clock=iter((10.0, 12.5)).__next__,
        id_factory=lambda: "turn-1",
    )

    result = session.prompt("Summarize the request.")

    assert result == TurnResult(
        status="success",
        session_id=record.session_id,
        run_id="run-1",
        turn_id="turn-1",
        content="Done.",
    )
    assert provider.received_messages == (
        AgentMessage(role="system", content="Use brief answers."),
        AgentMessage(role="user", content="Summarize the request."),
    )
    assert store.load(record.session_id).messages == (
        AgentMessage(role="user", content="Summarize the request."),
        AgentMessage(role="assistant", content="Done."),
    )
    assert [type(event) for event in events] == [
        TurnStartedEvent,
        MessageEvent,
        MessageEvent,
        TurnFinishedEvent,
    ]
    started = events[0]
    finished = events[-1]
    assert isinstance(started, TurnStartedEvent)
    assert started.run_id == "run-1"
    assert started.turn_id == "turn-1"
    assert started.started_at == 10.0
    assert isinstance(finished, TurnFinishedEvent)
    assert finished.run_id == "run-1"
    assert finished.result == result
    assert finished.duration == 2.5


def test_coding_session_aggregates_usage_across_provider_continuations() -> None:
    store = MemorySessionStore()
    record = store.create()
    registry = ExtensionRegistry()
    register_sample_tools(registry)
    session = CodingSession(
        provider=UsageProvider(
            responses=[
                ModelResponse(
                    tool_call=ToolCall(
                        name="word_count",
                        arguments={"text": "one two"},
                        call_id="call-1",
                    ),
                    usage=Usage(
                        input_tokens=10,
                        output_tokens=2,
                        cache_tokens=4,
                        cost=0.001,
                        currency="USD",
                    ),
                ),
                ModelResponse(
                    content="Finished.",
                    usage=Usage(
                        input_tokens=20,
                        output_tokens=3,
                        cost=0.002,
                        currency="USD",
                    ),
                ),
            ]
        ),
        session_store=store,
        session_id=record.session_id,
        executor=registry,
        id_factory=lambda: "turn-1",
    )

    result = session.prompt("Count the words.")

    assert result == TurnResult(
        status="success",
        session_id=record.session_id,
        run_id=session.run_id,
        turn_id="turn-1",
        content="Finished.",
        usage=Usage(
            input_tokens=30,
            output_tokens=5,
            cache_tokens=4,
            cost=0.003,
            currency="USD",
        ),
    )


def test_coding_session_does_not_sum_costs_in_mixed_currencies() -> None:
    store = MemorySessionStore()
    record = store.create()
    registry = ExtensionRegistry()
    register_sample_tools(registry)
    session = CodingSession(
        provider=UsageProvider(
            responses=[
                ModelResponse(
                    tool_call=ToolCall(
                        name="word_count",
                        arguments={"text": "one"},
                        call_id="call-1",
                    ),
                    usage=Usage(input_tokens=10, cost=0.001, currency="USD"),
                ),
                ModelResponse(
                    content="Finished.",
                    usage=Usage(output_tokens=2, cost=0.002, currency="EUR"),
                ),
            ]
        ),
        session_store=store,
        session_id=record.session_id,
        executor=registry,
        id_factory=lambda: "turn-1",
    )

    result = session.prompt("Finish the task.")

    assert result.usage == Usage(input_tokens=10, output_tokens=2)


def test_coding_session_returns_provider_failure_as_structured_error() -> None:
    store = MemorySessionStore()
    record = store.create()
    events = []
    session = CodingSession(
        provider=FailingProvider(),
        session_store=store,
        session_id=record.session_id,
        run_id="run-1",
        on_event=events.append,
        id_factory=lambda: "turn-1",
    )

    result = session.prompt("Try the request.")

    assert result.status == "error"
    assert result.session_id == record.session_id
    assert result.run_id == "run-1"
    assert result.turn_id
    assert result.error is not None
    assert "provider request failed: provider unavailable" in result.error
    assert isinstance(events[-1], TurnFinishedEvent)
    assert events[-1].result == result
    assert store.load(record.session_id).messages == (
        AgentMessage(role="user", content="Try the request."),
    )


def test_coding_session_cancels_an_active_tool_turn() -> None:
    store = MemorySessionStore()
    record = store.create()
    started = Event()
    events = []
    session = CodingSession(
        provider=ToolProvider(),
        session_store=store,
        session_id=record.session_id,
        run_id="run-1",
        executor=BlockingExecutor(started),
        id_factory=iter(("turn-1",)).__next__,
        on_event=events.append,
    )
    results: list[TurnResult] = []
    worker = Thread(
        target=lambda: results.append(session.prompt("Wait for the tool.")),
    )

    worker.start()
    assert started.wait(1)
    assert session.cancel() is True
    worker.join(5)

    assert not worker.is_alive()
    assert results == [
        TurnResult(
            status="cancelled",
            session_id=record.session_id,
            run_id="run-1",
            turn_id="turn-1",
            error="tool execution cancelled",
        )
    ]
    assert isinstance(events[-1], TurnFinishedEvent)
    assert events[-1].result == results[0]


def test_coding_session_forwards_live_tool_output() -> None:
    store = MemorySessionStore()
    record = store.create()
    output: list[tuple[str, str]] = []

    class OutputExecutor:
        @property
        def tools(self) -> tuple[ToolDefinition, ...]:
            return (ToolDefinition("bash", "Run a command.", {}),)

        def invoke(self, name: str, arguments: dict[str, object]) -> str:
            raise AssertionError("context-aware invocation is required")

        def invoke_with_context(
            self,
            name: str,
            arguments: dict[str, object],
            context: ToolExecutionContext,
        ) -> str:
            assert context.on_output is not None
            context.on_output("stdout", "hello\n")
            return "done"

    session = CodingSession(
        provider=UsageProvider(
            responses=[
                ModelResponse(
                    tool_call=ToolCall(
                        name="bash",
                        arguments={},
                        call_id="call-1",
                    )
                ),
                ModelResponse(content="finished"),
            ]
        ),
        session_store=store,
        session_id=record.session_id,
        executor=OutputExecutor(),
        on_tool_output=lambda stream, chunk: output.append((stream, chunk)),
    )

    result = session.prompt("run the command")

    assert result.status == "success"
    assert output == [("stdout", "hello\n")]


def test_coding_session_rejects_concurrent_prompt_with_a_correlated_error() -> None:
    store = MemorySessionStore()
    record = store.create()
    started = Event()
    session = CodingSession(
        provider=ToolProvider(),
        session_store=store,
        session_id=record.session_id,
        run_id="run-1",
        executor=BlockingExecutor(started),
        id_factory=iter(("turn-1", "turn-2")).__next__,
    )
    worker = Thread(target=lambda: session.prompt("Wait for the tool."))

    worker.start()
    assert started.wait(1)
    result = session.prompt("Run concurrently.")
    assert result == TurnResult(
        status="error",
        session_id=record.session_id,
        run_id="run-1",
        turn_id="turn-2",
        error="session is already running",
    )
    assert session.cancel() is True
    worker.join(5)
    assert not worker.is_alive()


def test_coding_session_returns_persistence_failure_as_structured_error() -> None:
    store = FailingStore()
    record = store.create()
    session = CodingSession(
        provider=CapturingProvider(),
        session_store=store,
        session_id=record.session_id,
        run_id="run-1",
    )

    result = session.prompt("Persist this request.")

    assert result.status == "error"
    assert result.run_id == "run-1"
    assert result.error is not None
    assert "persistence unavailable" in result.error
