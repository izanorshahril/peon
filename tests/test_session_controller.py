"""Tests for SessionController prompt dispatch."""

from dataclasses import dataclass
from collections.abc import Sequence
from threading import Event, Thread

from peon.agent import (
    AgentMessage,
    ModelResponse,
    ToolCall,
    ToolDefinition,
    ToolExecutionContext,
    ToolExecutor,
    Usage,
)
from peon.app.coding_session import (
    CodingSession,
    MessageEvent,
    TurnFinishedEvent,
    TurnStartedEvent,
    TurnResult,
)
from peon.app.session_controller import PromptIntent, SessionController
from peon.app.resources import ResourceInventory
from peon.app.sessions import MemorySessionStore


@dataclass
class EchoProvider:
    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        return ModelResponse(content="echo")


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
class UsageProvider:
    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        return ModelResponse(
            content="done",
            usage=Usage(input_tokens=10, output_tokens=5),
        )


def _make_controller(**kwargs):
    store = MemorySessionStore()
    record = store.create()
    defaults = dict(
        provider=EchoProvider(),
        session_store=store,
        session_id=record.session_id,
    )
    defaults.update(kwargs)
    return SessionController(**defaults)


# --- Basic dispatch ---

def test_dispatch_returns_success():
    controller = _make_controller()
    result = controller.dispatch(PromptIntent("hello"))
    assert result.status == "success"
    assert result.content == "echo"


def test_dispatch_preserves_session_ids():
    store = MemorySessionStore()
    record = store.create()
    controller = SessionController(
        provider=EchoProvider(),
        session_store=store,
        session_id=record.session_id,
        run_id="test-run",
    )
    assert controller.session_id == record.session_id
    assert controller.run_id == "test-run"
    result = controller.dispatch(PromptIntent("x"))
    assert result.session_id == record.session_id
    assert result.run_id == "test-run"


def test_dispatch_preserve_whitespace():
    """Whitespace flag forwards to CodingSession.prompt."""
    controller = _make_controller()
    result = controller.dispatch(PromptIntent("  spaced  ", preserve_whitespace=True))
    assert result.status == "success"


# --- Events ---

def test_dispatch_emits_start_messages_finish():
    events = []
    controller = _make_controller(on_event=events.append)
    result = controller.dispatch(PromptIntent("hello"))

    assert result.status == "success"
    assert len(events) >= 3
    assert isinstance(events[0], TurnStartedEvent)
    assert isinstance(events[-1], TurnFinishedEvent)

    message_events = [e for e in events if isinstance(e, MessageEvent)]
    assert len(message_events) >= 1

    # All events carry matching session/run/turn IDs
    turn_id = events[0].turn_id
    for event in events:
        assert event.session_id == controller.session_id
        assert event.run_id == controller.run_id
        assert event.turn_id == turn_id


def test_dispatch_events_match_direct_session():
    """Controller events should match what CodingSession produces directly."""
    controller_events = []
    session_events = []

    store1 = MemorySessionStore()
    record1 = store1.create()
    controller = SessionController(
        provider=EchoProvider(),
        session_store=store1,
        session_id=record1.session_id,
        on_event=controller_events.append,
        id_factory=lambda: "fixed-turn",
    )

    store2 = MemorySessionStore()
    record2 = store2.create()
    session = CodingSession(
        provider=EchoProvider(),
        session_store=store2,
        session_id=record2.session_id,
        on_event=session_events.append,
        id_factory=lambda: "fixed-turn",
    )

    controller.dispatch(PromptIntent("hello"))
    session.prompt("hello")

    assert len(controller_events) == len(session_events)
    for ce, se in zip(controller_events, session_events):
        assert type(ce) is type(se)


# --- Error handling ---

def test_dispatch_provider_error():
    controller = _make_controller(provider=FailingProvider())
    result = controller.dispatch(PromptIntent("hello"))
    assert result.status == "error"
    assert "provider unavailable" in (result.error or "")


def test_dispatch_persistence_failure():
    class FailingStore(MemorySessionStore):
        def append(self, session_id, message):
            raise RuntimeError("store broken")

    store = FailingStore()
    record = store.create()
    controller = SessionController(
        provider=EchoProvider(),
        session_store=store,
        session_id=record.session_id,
    )
    result = controller.dispatch(PromptIntent("hello"))
    assert result.status == "error"
    assert "store broken" in (result.error or "")


# --- Cancellation ---

def test_cancel_no_active_prompt():
    controller = _make_controller()
    assert controller.cancel() is False


def test_cancel_during_active_prompt():
    started = Event()
    proceed = Event()

    @dataclass
    class SlowProvider:
        def complete(
            self,
            *,
            messages: Sequence[AgentMessage],
            tools: Sequence[ToolDefinition] = (),
            model: str | None = None,
        ) -> ModelResponse:
            started.set()
            proceed.wait(timeout=5)
            return ModelResponse(content="late")

    controller = _make_controller(provider=SlowProvider())
    result_holder = []

    def run():
        result_holder.append(controller.dispatch(PromptIntent("go")))

    thread = Thread(target=run)
    thread.start()
    started.wait(timeout=5)
    assert controller.cancel() is True
    proceed.set()
    thread.join(timeout=5)
    assert len(result_holder) == 1
    # Provider returned normally but cancel was requested
    result = result_holder[0]
    assert result.status == "cancelled"


# --- Messages property ---

def test_messages_after_dispatch():
    controller = _make_controller()
    assert len(controller.messages) == 0
    controller.dispatch(PromptIntent("hello"))
    messages = controller.messages
    assert len(messages) >= 2  # user + assistant at minimum
    assert messages[0].role == "user"


# --- Usage ---

def test_dispatch_usage_forwarded():
    controller = _make_controller(provider=UsageProvider())
    result = controller.dispatch(PromptIntent("hello"))
    assert result.status == "success"
    assert result.usage is not None
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 5


# --- Session property ---

def test_session_property_exposes_inner():
    controller = _make_controller()
    assert isinstance(controller.session, CodingSession)
    assert controller.session.session_id == controller.session_id


# --- PromptIntent ---

def test_prompt_intent_frozen():
    intent = PromptIntent("hello")
    assert intent.text == "hello"
    assert intent.preserve_whitespace is False
    try:
        intent.text = "mutated"  # type: ignore[misc]
        assert False, "should be frozen"
    except (AttributeError, TypeError):
        pass


def test_prompt_intent_with_whitespace():
    intent = PromptIntent("  hello  ", preserve_whitespace=True)
    assert intent.preserve_whitespace is True
