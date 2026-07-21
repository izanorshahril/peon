"""Tests for SessionController prompt dispatch."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
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
from peon.app.session_controller import (
    CommandErrorOutcome,
    CommandIntent,
    ContinuationResponseIntent,
    ForkSessionIntent,
    HelpOutcome,
    LogoutIntent,
    LogoutOptionsOutcome,
    LogoutSuccessOutcome,
    ModelOptionsOutcome,
    ModelSelectIntent,
    NewSessionIntent,
    PromptIntent,
    ProviderSetupIntent,
    ProviderSetupStepOutcome,
    ReasoningOutcome,
    ResumeOptionsOutcome,
    ResumeSelectIntent,
    ResumeSessionIntent,
    SessionController,
    SessionInfoOutcome,
    SessionTransitionOutcome,
    SkillsOutcome,
    ToolsOutcome,
)
from peon.app.cli import ProviderConfig
from peon.app.config import UiConfig
from peon.app.resources import ResourceInventory, SkillResource
from peon.app.sessions import MemorySessionStore
from peon.extensions import ExtensionRegistry


class MemoryConfigStore:
    def __init__(self, configurations: tuple[ProviderConfig, ...] = ()) -> None:
        self.configurations = list(configurations)
        self.ui_configuration = UiConfig()

    def load(self) -> ProviderConfig | None:
        return self.configurations[-1] if self.configurations else None

    def load_all(self) -> tuple[ProviderConfig, ...]:
        return tuple(self.configurations)

    def save(self, config: ProviderConfig) -> None:
        for index, existing in enumerate(self.configurations):
            if existing.name == config.name and existing.base_url == config.base_url:
                self.configurations[index] = config
                return
        self.configurations.append(config)

    def delete(self, config: ProviderConfig) -> None:
        self.configurations = [
            existing
            for existing in self.configurations
            if existing != config
        ]


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


# --- Command Intent Tests ---

def test_dispatch_command_help():
    controller = _make_controller()
    outcome = controller.dispatch_command(CommandIntent("/help"))
    assert isinstance(outcome, HelpOutcome)
    assert "/help" in outcome.help_text
    assert len(outcome.commands) > 0


def test_dispatch_command_tools():
    registry = ExtensionRegistry()
    registry.register_tool(
        name="test_tool",
        description="A test tool",
        parameters={"type": "object"},
        handler=lambda arguments: "ok",
    )
    controller = _make_controller(executor=registry, enabled_tools=["test_tool"])
    outcome = controller.dispatch_command(CommandIntent("/tools"))
    assert isinstance(outcome, ToolsOutcome)
    assert len(outcome.tools) == 1
    assert outcome.tools[0].name == "test_tool"
    assert outcome.tools[0].enabled is True


def test_dispatch_command_skills():
    resources = ResourceInventory(
        skills=(
            SkillResource(
                name="sample_skill",
                description="Sample skill description",
                content="Skill body content",
                path=Path("path/to/skill/SKILL.md"),
                base_directory=Path("path/to/skill"),
                source="project",
            ),
        )
    )
    controller = _make_controller(resources=resources)
    outcome = controller.dispatch_command(CommandIntent("/skills"))
    assert isinstance(outcome, SkillsOutcome)
    assert len(outcome.skills) >= 1
    assert any(s.name == "sample_skill" for s in outcome.skills)


def test_dispatch_command_skill_selection():
    resources = ResourceInventory(
        skills=(
            SkillResource(
                name="sample_skill",
                description="Sample skill description",
                content="Skill body content",
                path=Path("path/to/skill/SKILL.md"),
                base_directory=Path("path/to/skill"),
                source="project",
            ),
        )
    )
    controller = _make_controller(resources=resources)
    outcome = controller.dispatch_command(CommandIntent("/skill:sample_skill"))
    assert isinstance(outcome, SkillsOutcome)
    assert outcome.selected_skill is not None
    assert outcome.selected_skill.name == "sample_skill"
    assert outcome.selected_skill.status == "loaded"
    assert outcome.selected_skill.content == "Skill body content"


def test_dispatch_command_session_info():
    controller = _make_controller()
    outcome = controller.dispatch_command(CommandIntent("/session"))
    assert isinstance(outcome, SessionInfoOutcome)
    assert outcome.session_id == controller.session_id
    assert outcome.message_count == 0
    assert outcome.interaction_count == 0


def test_dispatch_command_reasoning():
    controller = _make_controller(reasoning_effort="low", reasoning_choices=("none", "low", "high"))
    outcome = controller.dispatch_command(CommandIntent("/reasoning"))
    assert isinstance(outcome, ReasoningOutcome)
    assert outcome.supported is True
    assert outcome.current == "high"
    assert outcome.updated is True

    # Change effort explicitly
    outcome_updated = controller.dispatch_command(CommandIntent("/reasoning none"))
    assert isinstance(outcome_updated, ReasoningOutcome)
    assert outcome_updated.current == "none"
    assert outcome_updated.updated is True


def test_dispatch_command_unknown():
    controller = _make_controller()
    outcome = controller.dispatch_command(CommandIntent("/nonexistent"))
    assert isinstance(outcome, CommandErrorOutcome)
    assert "Unknown command" in outcome.error


def test_dispatch_command_reserved():
    controller = _make_controller()
    outcome = controller.dispatch_command(CommandIntent("/compact"))
    assert isinstance(outcome, CommandErrorOutcome)
    assert "reserved" in outcome.error


def test_dispatch_new_session():
    controller = _make_controller()
    old_id = controller.session_id
    outcome = controller.dispatch(NewSessionIntent())
    assert isinstance(outcome, SessionTransitionOutcome)
    assert outcome.action == "new"
    assert outcome.session_id != old_id
    assert outcome.parent_id == old_id
    assert controller.session_id == outcome.session_id


def test_dispatch_resume_session_list_and_select():
    store = MemorySessionStore()
    s1 = store.create()
    store.append(s1.session_id, AgentMessage(role="user", content="hello session 1"))
    s2 = store.create()
    store.append(s2.session_id, AgentMessage(role="user", content="hello session 2"))

    active = store.create()
    controller = _make_controller(session_store=store, session_id=active.session_id)

    # Request resume listing
    outcome = controller.dispatch(ResumeSessionIntent())
    assert isinstance(outcome, ResumeOptionsOutcome)
    assert len(outcome.options) == 2
    token = outcome.continuation_token

    # Select via continuation token
    select_outcome = controller.dispatch(ResumeSelectIntent(continuation_token=token, selection="1"))
    assert isinstance(select_outcome, SessionTransitionOutcome)
    assert select_outcome.action == "resume"
    assert select_outcome.session_id in (s1.session_id, s2.session_id)
    assert controller.session_id == select_outcome.session_id


def test_dispatch_resume_single_use_token_reuse_fails():
    store = MemorySessionStore()
    s1 = store.create()
    store.append(s1.session_id, AgentMessage(role="user", content="hello"))
    active = store.create()
    controller = _make_controller(session_store=store, session_id=active.session_id)

    outcome = controller.dispatch(ResumeSessionIntent())
    assert isinstance(outcome, ResumeOptionsOutcome)
    token = outcome.continuation_token

    # First use succeeds
    succ = controller.dispatch(ResumeSelectIntent(continuation_token=token, selection="1"))
    assert isinstance(succ, SessionTransitionOutcome)

    # Reuse of same token fails
    fail = controller.dispatch(ResumeSelectIntent(continuation_token=token, selection="1"))
    assert isinstance(fail, CommandErrorOutcome)
    assert "invalid, expired, or already used" in fail.error


def test_dispatch_fork_session():
    store = MemorySessionStore()
    active = store.create()
    store.append(active.session_id, AgentMessage(role="user", content="parent prompt"))
    controller = _make_controller(session_store=store, session_id=active.session_id)

    outcome = controller.dispatch(ForkSessionIntent(name="my-fork"))
    assert isinstance(outcome, SessionTransitionOutcome)
    assert outcome.action == "fork"
    assert outcome.name == "my-fork"
    assert outcome.parent_id == active.session_id
    assert controller.session_id == outcome.session_id


def test_dispatch_command_session_transitions():
    store = MemorySessionStore()
    active = store.create()
    controller = _make_controller(session_store=store, session_id=active.session_id)

    new_outcome = controller.dispatch_command(CommandIntent("/new"))
    assert isinstance(new_outcome, SessionTransitionOutcome)
    assert new_outcome.action == "new"

    fork_outcome = controller.dispatch_command(CommandIntent("/fork branch"))
    assert isinstance(fork_outcome, SessionTransitionOutcome)
    assert fork_outcome.action == "fork"
    assert fork_outcome.name == "branch"


def test_dispatch_model_select_no_saved_models():
    controller = _make_controller()
    outcome = controller.dispatch(ModelSelectIntent())
    assert isinstance(outcome, CommandErrorOutcome)
    assert "No saved models" in outcome.error


def test_dispatch_provider_setup():
    controller = _make_controller()
    outcome = controller.dispatch(ProviderSetupIntent())
    assert isinstance(outcome, ProviderSetupStepOutcome)
    assert outcome.step == "provider_type"
    assert outcome.continuation_token != ""


def test_dispatch_logout_no_saved_providers():
    controller = _make_controller()
    outcome = controller.dispatch(LogoutIntent())
    assert isinstance(outcome, CommandErrorOutcome)
    assert "No saved providers" in outcome.error


def test_dispatch_model_select_with_saved_models():
    c1 = ProviderConfig(name="alpha", model="model-a", models=("model-a",), base_url="http://a.test")
    c2 = ProviderConfig(name="beta", model="model-b", models=("model-b",), base_url="http://b.test")
    store = MemoryConfigStore((c1, c2))
    controller = _make_controller()

    outcome = controller.dispatch_model_select(ModelSelectIntent(), config_store=store)
    assert isinstance(outcome, ModelOptionsOutcome)
    assert len(outcome.options) == 2
    assert outcome.continuation_token is not None

    select_outcome = controller.dispatch(
        ContinuationResponseIntent(continuation_token=outcome.continuation_token, response="2")
    )
    assert isinstance(select_outcome, ModelOptionsOutcome)
    assert select_outcome.current_model == "model-b"
    assert select_outcome.updated is True


def test_dispatch_logout_with_saved_providers():
    c1 = ProviderConfig(name="alpha", model="model-a", base_url="http://a.test")
    store = MemoryConfigStore((c1,))
    controller = _make_controller()

    outcome = controller.dispatch_logout(LogoutIntent(), config_store=store)
    assert isinstance(outcome, LogoutOptionsOutcome)
    assert len(outcome.options) == 1
    assert outcome.continuation_token is not None

    logout_outcome = controller.dispatch(
        ContinuationResponseIntent(continuation_token=outcome.continuation_token, response="1")
    )
    assert isinstance(logout_outcome, LogoutSuccessOutcome)
    assert logout_outcome.removed_provider_name == "alpha"


def test_dispatch_continuation_response_invalid_token():
    controller = _make_controller()
    outcome = controller.dispatch(
        ContinuationResponseIntent(continuation_token="nonexistent", response="1")
    )
    assert isinstance(outcome, CommandErrorOutcome)
    assert "invalid, expired, or already used" in outcome.error
