"""Host-neutral session controller for prompt, command, and session transition dispatch."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any, Literal, TypeAlias, cast, overload
from uuid import uuid4

from peon.agent import (
    AgentContext,
    AgentMessage,
    ModelProvider,
    ToolExecutionContext,
    ToolExecutor,
    Usage,
)
from peon.agent.tracing import TraceSink
from peon.extensions import ExtensionRegistry
from .coding_session import (
    CodingSession,
    EventHandler,
    MessageEvent,
    CommandOutcomeEvent,
    SelectionRequestEvent,
    RunLimits,
    SessionEvent,
    StopReason,
    ToolFinishedEvent,
    ToolOutputEvent,
    ToolStartedEvent,
    TurnFinishedEvent,
    TurnResult,
    TurnStartedEvent,
)
from .commands import (
    DEFAULT_COMMAND_CATALOG,
    CommandDefinition,
)
from .config import (
    ProviderConfig,
    ProviderConfigStore,
    SavedModel,
    provider_id,
    saved_model_choices,
    select_saved_model,
)
from .resources import (
    ResourceInventory,
    apply_resource_prompt,
    conversation_messages_without_resource_prompt,
    load_skill_into_context,
)
from .sessions import (
    SessionRecord,
    SessionStore,
    SessionStoreError,
    create_session,
    discard_empty_session,
    format_session_age,
    format_session_summary,
    select_session,
    session_first_prompt,
    session_interaction_count,
)


@dataclass(frozen=True, slots=True)
class PromptIntent:
    """Typed prompt request for dispatch through the session controller."""

    text: str
    preserve_whitespace: bool = False
    on_event: EventHandler | None = None


@dataclass(frozen=True, slots=True)
class CommandIntent:
    """Typed slash command request for dispatch through the session controller."""

    command: str


@dataclass(frozen=True, slots=True)
class NewSessionIntent:
    """Typed request to create a fresh conversation session."""

    pass


@dataclass(frozen=True, slots=True)
class ResumeSessionIntent:
    """Typed request to list sessions for resuming or directly resume by target."""

    target: str | None = None


@dataclass(frozen=True, slots=True)
class ResumeSelectIntent:
    """Typed request to select a session to resume using a single-use continuation token."""

    continuation_token: str
    selection: str


@dataclass(frozen=True, slots=True)
class ForkSessionIntent:
    """Typed request to fork the active conversation session."""

    name: str | None = None


@dataclass(frozen=True, slots=True)
class ModelSelectIntent:
    """Typed request to list models or directly select a model."""

    target: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderSetupIntent:
    """Typed request to initiate provider setup flow."""

    pass


@dataclass(frozen=True, slots=True)
class SettingsIntent:
    """Typed request to view or update application settings."""

    setting: str | None = None
    value: str | None = None


@dataclass(frozen=True, slots=True)
class LogoutIntent:
    """Typed request to list providers for logout or remove active provider."""

    target: str | None = None


@dataclass(frozen=True, slots=True)
class ContinuationResponseIntent:
    """Typed response to a single-use continuation token for multi-step flows."""

    continuation_token: str
    response: str | Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ToolStatus:
    """Status of a tool registered with the controller."""

    name: str
    description: str
    registered: bool
    enabled: bool


@dataclass(frozen=True, slots=True)
class SkillStatus:
    """Status of a skill discovered or loaded by the controller."""

    name: str
    status: Literal["loaded", "registered", "available", "unknown"]
    path: str | Path | None = None
    content: str | None = None


@dataclass(frozen=True, slots=True)
class HelpOutcome:
    """Outcome of executing the /help command."""

    help_text: str
    commands: tuple[CommandDefinition, ...]


@dataclass(frozen=True, slots=True)
class ToolsOutcome:
    """Outcome of executing the /tools command."""

    tools: tuple[ToolStatus, ...]


@dataclass(frozen=True, slots=True)
class SkillsOutcome:
    """Outcome of executing the /skills or /skill:<name> command."""

    skills: tuple[SkillStatus, ...]
    selected_skill: SkillStatus | None = None


@dataclass(frozen=True, slots=True)
class SessionInfoOutcome:
    """Outcome of executing the /session command."""

    session_id: str
    message_count: int
    interaction_count: int
    usage: Usage | None
    record: SessionRecord | None


@dataclass(frozen=True, slots=True)
class ReasoningOutcome:
    """Outcome of executing the /reasoning command."""

    supported: bool
    current: str | None
    choices: tuple[str, ...]
    updated: bool = False


@dataclass(frozen=True, slots=True)
class ResumeOption:
    """A semantic choice for resuming a saved conversation session."""

    option_id: str
    session_id: str
    summary: str
    first_prompt: str
    interaction_count: int
    age_display: str
    name: str | None = None


@dataclass(frozen=True, slots=True)
class ResumeOptionsOutcome:
    """Outcome listing available sessions to resume with a continuation token."""

    options: tuple[ResumeOption, ...]
    continuation_token: str


@dataclass(frozen=True, slots=True)
class SessionTransitionOutcome:
    """Outcome of a session lifecycle transition (new, resume, fork)."""

    action: Literal["new", "resume", "fork"]
    session_id: str
    parent_id: str | None = None
    name: str | None = None
    record: SessionRecord | None = None
    messages: tuple[AgentMessage, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelOption:
    """A semantic choice for selecting a saved provider model."""

    option_id: str
    label: str
    provider_name: str
    model_name: str
    active: bool = False


@dataclass(frozen=True, slots=True)
class ModelOptionsOutcome:
    """Outcome listing available models with a continuation token or active update."""

    options: tuple[ModelOption, ...]
    current_model: str | None
    continuation_token: str | None = None
    updated: bool = False


@dataclass(frozen=True, slots=True)
class ProviderSetupStepOutcome:
    """Outcome requesting user input during multi-step provider setup."""

    step: str
    prompt: str
    is_secret: bool
    continuation_token: str


@dataclass(frozen=True, slots=True)
class ProviderSuccessOutcome:
    """Outcome when provider setup or configuration succeeds."""

    provider_name: str
    model_name: str
    config: Any


@dataclass(frozen=True, slots=True)
class LogoutOptionsOutcome:
    """Outcome listing saved providers for removal with a continuation token."""

    options: tuple[tuple[str, str], ...]  # (option_id, provider_name)
    continuation_token: str


@dataclass(frozen=True, slots=True)
class LogoutSuccessOutcome:
    """Outcome when a provider is removed."""

    removed_provider_name: str
    active_provider_name: str | None
    active_config: ProviderConfig | None = None


@dataclass(frozen=True, slots=True)
class SettingOption:
    """A configurable application or provider setting option."""

    key: str
    label: str
    current_value: str
    value_kind: str
    choices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SettingsOptionsOutcome:
    """Outcome listing configurable settings."""

    settings: tuple[SettingOption, ...]
    continuation_token: str | None = None


@dataclass(frozen=True, slots=True)
class SettingsUpdatedOutcome:
    """Outcome when a setting has been updated."""

    setting: str
    value: str
    updated: bool = True


@dataclass(frozen=True, slots=True)
class ShellIntent:
    """Typed request for direct visible or hidden shell command execution."""

    command: str
    hidden: bool = False


@dataclass(frozen=True, slots=True)
class ShellResultOutcome:
    """Outcome of direct shell command execution."""

    command: str
    output: str
    exit_code: int = 0
    hidden: bool = False
    turn_result: TurnResult | None = None


@dataclass(frozen=True, slots=True)
class ShellErrorOutcome:
    """Outcome when direct shell command execution fails."""

    command: str
    error: str


@dataclass(frozen=True, slots=True)
class CommandErrorOutcome:
    """Outcome when a command fails or is unavailable."""

    command: str
    error: str


CommandOutcome: TypeAlias = (
    HelpOutcome
    | ToolsOutcome
    | SkillsOutcome
    | SessionInfoOutcome
    | ReasoningOutcome
    | ResumeOptionsOutcome
    | SessionTransitionOutcome
    | ModelOptionsOutcome
    | ProviderSetupStepOutcome
    | ProviderSuccessOutcome
    | LogoutOptionsOutcome
    | LogoutSuccessOutcome
    | SettingsOptionsOutcome
    | SettingsUpdatedOutcome
    | ShellResultOutcome
    | ShellErrorOutcome
    | CommandErrorOutcome
)

Intent: TypeAlias = (
    PromptIntent
    | CommandIntent
    | NewSessionIntent
    | ResumeSessionIntent
    | ResumeSelectIntent
    | ForkSessionIntent
    | ModelSelectIntent
    | ProviderSetupIntent
    | SettingsIntent
    | LogoutIntent
    | ContinuationResponseIntent
    | ShellIntent
)


class SessionController:
    """Dispatch typed prompt, command, and session transition intents.

    Composes :class:`CodingSession` rather than duplicating the agent loop.
    Every host dispatches prompts, commands, and transitions through this
    controller to get equivalent events, results, persistence, cancellation,
    resources, and tool behavior.
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
        enabled_tools: tuple[str, ...] | Sequence[str] | None = None,
        reasoning_effort: str | None = None,
        reasoning_choices: tuple[str, ...] | Sequence[str] = ("none", "low", "medium", "high"),
        on_event: EventHandler | None = None,
        on_tool_output: Callable[[str, str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        id_factory: Callable[[], str] = lambda: uuid4().hex,
        trace_sink: TraceSink | None = None,
        trace_provider: str | None = None,
        trace_utc_clock: Callable[[], datetime] | None = None,
        event_utc_clock: Callable[[], datetime] | None = None,
        event_sequence_start: int = 0,
        limits: RunLimits | None = None,
        journal_sink: Any | None = None,
    ) -> None:
        self.provider = provider
        self.session_store = session_store
        self._context = context if context is not None else AgentContext()
        self._executor = executor
        self._model = model
        self._resources = resources
        self._enabled_tools = tuple(enabled_tools) if enabled_tools is not None else None
        self._reasoning_effort = reasoning_effort
        self._reasoning_choices = tuple(reasoning_choices)
        self._id_factory = id_factory
        self._trace_sink = trace_sink
        self._trace_provider = trace_provider
        self._trace_utc_clock = trace_utc_clock
        self._event_utc_clock = event_utc_clock or (
            lambda: datetime.now(timezone.utc)
        )
        self._limits = limits
        self._journal_sink = journal_sink
        self._resume_tokens: dict[str, dict[str, str]] = {}
        self._continuation_tokens: dict[str, dict[str, object]] = {}
        self._session = CodingSession(
            provider=provider,
            session_store=session_store,
            session_id=session_id,
            run_id=run_id,
            context=self._context,
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
            event_utc_clock=self._event_utc_clock,
            event_sequence_start=event_sequence_start,
            limits=limits,
            journal_sink=journal_sink,
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

        Exposed for hosts that need internal access during migration.
        """
        return self._session

    @overload
    def dispatch(self, intent: PromptIntent) -> TurnResult: ...

    @overload
    def dispatch(self, intent: CommandIntent) -> CommandOutcome: ...

    @overload
    def dispatch(self, intent: NewSessionIntent) -> SessionTransitionOutcome: ...

    @overload
    def dispatch(
        self, intent: ResumeSessionIntent
    ) -> ResumeOptionsOutcome | SessionTransitionOutcome | CommandErrorOutcome: ...

    @overload
    def dispatch(
        self, intent: ResumeSelectIntent
    ) -> SessionTransitionOutcome | CommandErrorOutcome: ...

    @overload
    def dispatch(
        self, intent: ForkSessionIntent
    ) -> SessionTransitionOutcome | CommandErrorOutcome: ...

    @overload
    def dispatch(
        self, intent: ModelSelectIntent
    ) -> ModelOptionsOutcome | CommandErrorOutcome: ...

    @overload
    def dispatch(
        self, intent: ProviderSetupIntent
    ) -> ProviderSetupStepOutcome | CommandErrorOutcome: ...

    @overload
    def dispatch(
        self, intent: LogoutIntent
    ) -> LogoutOptionsOutcome | LogoutSuccessOutcome | CommandErrorOutcome: ...

    @overload
    def dispatch(
        self, intent: ContinuationResponseIntent
    ) -> CommandOutcome: ...

    @overload
    def dispatch(
        self, intent: ShellIntent
    ) -> ShellResultOutcome | ShellErrorOutcome: ...

    def dispatch(
        self,
        intent: Intent,
    ) -> TurnResult | CommandOutcome:
        """Dispatch any typed intent to its corresponding handler."""
        if isinstance(intent, PromptIntent):
            return self._session.prompt(
                intent.text,
                preserve_task_whitespace=intent.preserve_whitespace,
                on_event=intent.on_event,
            )
        if isinstance(intent, CommandIntent):
            return self.dispatch_command(intent)
        if isinstance(intent, NewSessionIntent):
            return self.dispatch_new_session(intent)
        if isinstance(intent, ResumeSessionIntent):
            return self.dispatch_resume(intent)
        if isinstance(intent, ResumeSelectIntent):
            return self.dispatch_resume_select(intent)
        if isinstance(intent, ForkSessionIntent):
            return self.dispatch_fork(intent)
        if isinstance(intent, ModelSelectIntent):
            return self.dispatch_model_select(intent)
        if isinstance(intent, ProviderSetupIntent):
            return self.dispatch_provider_setup(intent)
        if isinstance(intent, SettingsIntent):
            return self.dispatch_settings(intent)
        if isinstance(intent, LogoutIntent):
            return self.dispatch_logout(intent)
        if isinstance(intent, ContinuationResponseIntent):
            return self.dispatch_continuation_response(intent)
        if isinstance(intent, ShellIntent):
            return self.dispatch_shell(intent)
        raise TypeError(f"Unknown intent type: {type(intent)}")

    def dispatch_command(self, intent: CommandIntent) -> CommandOutcome:
        outcome = self._dispatch_command(intent)
        self._emit_command_events(intent.command, outcome)
        return outcome

    def _dispatch_command(self, intent: CommandIntent) -> CommandOutcome:
        """Dispatch one informational or transition command intent."""
        raw_cmd = intent.command.strip()
        name = raw_cmd.split(maxsplit=1)[0]
        normalized_name = name.casefold()

        # Skill selection (/skill:<name>)
        if normalized_name.startswith("/skill:") and normalized_name != "/skill:":
            skill_name = name.split(":", maxsplit=1)[1]
            resource = (
                self._resources.find_skill(skill_name)
                if self._resources is not None
                else None
            )
            if resource is not None:
                load_skill_into_context(self._context, resource)
                selected = SkillStatus(
                    name=resource.name,
                    status="loaded",
                    path=str(resource.path) if resource.path is not None else None,
                    content=resource.content,
                )
                return SkillsOutcome(skills=self._get_all_skills(), selected_skill=selected)
            registered_skills = self._get_registered_skill_names()
            if skill_name in registered_skills:
                selected = SkillStatus(name=skill_name, status="registered")
                return SkillsOutcome(skills=self._get_all_skills(), selected_skill=selected)
            available_skills = self._get_available_skill_names()
            if skill_name in available_skills:
                selected = SkillStatus(name=skill_name, status="available")
                return SkillsOutcome(skills=self._get_all_skills(), selected_skill=selected)
            return CommandErrorOutcome(command=intent.command, error=f"Unknown skill: {skill_name}")

        invocation = DEFAULT_COMMAND_CATALOG.resolve(raw_cmd)
        if invocation is None:
            return CommandErrorOutcome(command=intent.command, error=f"Unknown command: {name}")

        definition = invocation.command
        if definition.availability == "reserved":
            return CommandErrorOutcome(
                command=definition.name,
                error=f"{definition.name} is reserved and is not available yet.",
            )

        cmd_id = definition.id

        if cmd_id == "help":
            return HelpOutcome(
                help_text=DEFAULT_COMMAND_CATALOG.help_text(),
                commands=DEFAULT_COMMAND_CATALOG.commands,
            )

        if cmd_id == "tools":
            return self._execute_tools_command()

        if cmd_id == "skills":
            return SkillsOutcome(skills=self._get_all_skills())

        if cmd_id == "session":
            return self._execute_session_command()

        if cmd_id == "reasoning":
            return self._execute_reasoning_command(invocation.argument)

        if cmd_id == "new":
            return self.dispatch_new_session(NewSessionIntent())

        if cmd_id == "resume":
            return self.dispatch_resume(ResumeSessionIntent(invocation.argument or None))

        if cmd_id == "fork":
            return self.dispatch_fork(ForkSessionIntent(invocation.argument or None))

        if cmd_id == "model":
            return self.dispatch_model_select(ModelSelectIntent(invocation.argument or None))

        if cmd_id == "provider":
            return self.dispatch_provider_setup(ProviderSetupIntent())

        if cmd_id == "settings":
            return self.dispatch_settings(SettingsIntent(invocation.argument or None))

        if cmd_id == "logout":
            return self.dispatch_logout(LogoutIntent(invocation.argument or None))

        return CommandErrorOutcome(command=raw_cmd, error=f"Command '{cmd_id}' is not an informational or transition command.")

    def _emit_command_events(self, command: str, outcome: CommandOutcome) -> None:
        options: tuple[Mapping[str, object], ...] = ()
        prompt: str | None = None
        if isinstance(outcome, ResumeOptionsOutcome):
            prompt = "Select a session to resume"
            options = tuple(
                {
                    "option_id": option.option_id,
                    "label": option.summary,
                    "session_id": option.session_id,
                }
                for option in outcome.options
            )
        elif isinstance(outcome, ModelOptionsOutcome) and outcome.continuation_token:
            prompt = "Select a model"
            options = tuple(
                {
                    "option_id": option.option_id,
                    "label": option.label,
                    "model": option.model_name,
                }
                for option in outcome.options
            )
        elif isinstance(outcome, LogoutOptionsOutcome):
            prompt = "Select a provider to remove"
            options = tuple(
                {"option_id": option_id, "label": provider_name}
                for option_id, provider_name in outcome.options
            )
        elif isinstance(outcome, ProviderSetupStepOutcome):
            prompt = outcome.prompt

        if prompt is not None:
            self._session._emit(
                SelectionRequestEvent(
                    session_id=self.session_id,
                    run_id=self.run_id,
                    turn_id=None,
                    prompt=prompt,
                    options=options,
                )
            )
        self._session._emit(
            CommandOutcomeEvent(
                session_id=self.session_id,
                run_id=self.run_id,
                turn_id=None,
                command=command,
                status=(
                    "error" if isinstance(outcome, CommandErrorOutcome) else "success"
                ),
                output=type(outcome).__name__,
            )
        )

    def dispatch_new_session(
        self,
        intent: NewSessionIntent | None = None,
    ) -> SessionTransitionOutcome:
        """Create a fresh conversation session, discarding empty previous sessions."""
        del intent
        if not any(message.role == "user" for message in self._context.messages):
            discard_empty_session(self.session_store, self.session_id)

        created = create_session(
            self.session_store,
            parent_id=self.session_id,
        )

        old_session_id = self.session_id
        self._context = AgentContext()
        if self._resources is not None:
            apply_resource_prompt(self._context, self._resources)

        self._session = CodingSession(
            provider=self.provider,
            session_store=self.session_store,
            session_id=created.session_id,
            run_id=self.run_id,
            context=self._context,
            executor=self._executor,
            model=self._model,
            resources=self._resources,
            on_event=self._session._on_event,
            on_tool_output=self._session._on_tool_output,
            clock=self._session._clock,
            id_factory=self._session._id_factory,
            trace_sink=self._trace_sink,
            trace_provider=self._trace_provider,
            trace_utc_clock=self._trace_utc_clock,
            limits=self._limits,
            journal_sink=self._journal_sink,
            event_utc_clock=self._event_utc_clock,
            event_sequence_start=self._session._event_sequence,
        )
        return SessionTransitionOutcome(
            action="new",
            session_id=created.session_id,
            parent_id=old_session_id,
            record=created,
            messages=self.messages,
        )

    def dispatch_resume(
        self,
        intent: ResumeSessionIntent | None = None,
    ) -> ResumeOptionsOutcome | SessionTransitionOutcome | CommandErrorOutcome:
        """List sessions to resume or directly resume a target session."""
        target = intent.target if intent is not None else None
        if not target:
            try:
                sessions = self.session_store.list_sessions()
            except (AttributeError, OSError, SessionStoreError):
                sessions = ()

            valid_sessions = [
                s for s in sessions
                if s.session_id != self.session_id and session_interaction_count(s) > 0
            ]
            options: list[ResumeOption] = []
            token_map: dict[str, str] = {}
            token = self._id_factory()

            for idx, record in enumerate(valid_sessions, 1):
                option_id = str(idx)
                prompt = session_first_prompt(record) or ""
                count = session_interaction_count(record)
                age = format_session_age(record.created_at)
                summary = format_session_summary(record)
                opt = ResumeOption(
                    option_id=option_id,
                    session_id=record.session_id,
                    summary=summary,
                    first_prompt=prompt,
                    interaction_count=count,
                    age_display=age,
                    name=record.name,
                )
                options.append(opt)
                token_map[option_id] = record.session_id
                token_map[record.session_id] = record.session_id
                if record.name:
                    token_map[record.name] = record.session_id

            self._resume_tokens[token] = token_map
            return ResumeOptionsOutcome(options=tuple(options), continuation_token=token)

        try:
            record = select_session(self.session_store, target)
        except (OSError, SessionStoreError) as error:
            return CommandErrorOutcome(command="resume", error=str(error))

        return self._switch_to_session("resume", record)

    def dispatch_resume_select(
        self,
        intent: ResumeSelectIntent,
    ) -> SessionTransitionOutcome | CommandErrorOutcome:
        """Select a session using a single-use continuation token."""
        token_map = self._resume_tokens.pop(intent.continuation_token, None)
        if token_map is None:
            return CommandErrorOutcome(
                command="resume",
                error=f"Continuation token '{intent.continuation_token}' is invalid, expired, or already used.",
            )

        session_id = token_map.get(intent.selection)
        if session_id is None:
            try:
                record = select_session(self.session_store, intent.selection)
            except (OSError, SessionStoreError) as error:
                return CommandErrorOutcome(command="resume", error=str(error))
        else:
            try:
                record = self.session_store.load(session_id)
            except (OSError, SessionStoreError) as error:
                return CommandErrorOutcome(command="resume", error=str(error))

        return self._switch_to_session("resume", record)

    def dispatch_fork(
        self,
        intent: ForkSessionIntent | None = None,
    ) -> SessionTransitionOutcome | CommandErrorOutcome:
        """Fork the active session into a new child session."""
        name = intent.name if intent is not None else None
        try:
            created = create_session(
                self.session_store,
                parent_id=self.session_id,
                name=name or None,
            )
        except (OSError, SessionStoreError) as error:
            return CommandErrorOutcome(command="fork", error=str(error))

        non_resource_messages = tuple(
            conversation_messages_without_resource_prompt(
                self._context.messages,
                self._resources,
            )
        )
        for message in non_resource_messages:
            try:
                self.session_store.append(created.session_id, message)
            except (OSError, SessionStoreError):
                pass

        self._context = AgentContext(messages=list(non_resource_messages))
        if self._resources is not None:
            apply_resource_prompt(self._context, self._resources)

        old_session_id = self.session_id
        self._session = CodingSession(
            provider=self.provider,
            session_store=self.session_store,
            session_id=created.session_id,
            run_id=self.run_id,
            context=self._context,
            executor=self._executor,
            model=self._model,
            resources=self._resources,
            on_event=self._session._on_event,
            on_tool_output=self._session._on_tool_output,
            clock=self._session._clock,
            id_factory=self._session._id_factory,
            trace_sink=self._trace_sink,
            trace_provider=self._trace_provider,
            trace_utc_clock=self._trace_utc_clock,
            limits=self._limits,
            journal_sink=self._journal_sink,
            event_utc_clock=self._event_utc_clock,
            event_sequence_start=self._session._event_sequence,
        )

        return SessionTransitionOutcome(
            action="fork",
            session_id=created.session_id,
            parent_id=old_session_id,
            name=name or None,
            record=created,
            messages=self.messages,
        )

    def dispatch_model_select(
        self,
        intent: ModelSelectIntent | None = None,
        config_store: ProviderConfigStore | None = None,
    ) -> ModelOptionsOutcome | CommandErrorOutcome:
        """Select a saved model or return available model choices."""
        target = intent.target if intent is not None else None
        store_configs: tuple[ProviderConfig, ...] = ()
        if config_store is not None:
            try:
                store_configs = config_store.load_all()
            except OSError:
                store_configs = ()

        choices = saved_model_choices(store_configs) if store_configs else ()

        if target is not None:
            if not choices:
                return CommandErrorOutcome(
                    command="model",
                    error="No saved models. Use /provider to discover models.",
                )
            try:
                choice = select_saved_model(target, choices)
            except Exception as error:
                return CommandErrorOutcome(command="model", error=str(error))

            self._model = choice.model
            options = tuple(
                ModelOption(
                    option_id=str(idx),
                    label=c.label,
                    provider_name=c.config.name,
                    model_name=c.model,
                    active=(c.model == choice.model),
                )
                for idx, c in enumerate(choices, 1)
            )
            return ModelOptionsOutcome(
                options=options,
                current_model=choice.model,
                updated=True,
            )

        if not choices:
            return CommandErrorOutcome(
                command="model",
                error="No saved models. Use /provider to discover models.",
            )

        token = self._id_factory()
        token_map = {str(idx): c for idx, c in enumerate(choices, 1)}
        self._continuation_tokens[token] = {
            "type": "model",
            "map": token_map,
            "choices": choices,
        }

        options = tuple(
            ModelOption(
                option_id=str(idx),
                label=c.label,
                provider_name=c.config.name,
                model_name=c.model,
                active=(c.model == self._model),
            )
            for idx, c in enumerate(choices, 1)
        )
        return ModelOptionsOutcome(
            options=options,
            current_model=self._model,
            continuation_token=token,
            updated=False,
        )

    def dispatch_provider_setup(
        self,
        intent: ProviderSetupIntent | None = None,
        config_store: ProviderConfigStore | None = None,
    ) -> ProviderSetupStepOutcome:
        """Start multi-step provider connection setup."""
        del intent
        token = self._id_factory()
        self._continuation_tokens[token] = {
            "type": "provider_step",
            "step": "provider_type",
            "data": {},
            "config_store": config_store,
        }
        return ProviderSetupStepOutcome(
            step="provider_type",
            prompt="Select provider type (1. openai-compatible, 2. custom, 3. github-copilot):",
            is_secret=False,
            continuation_token=token,
        )

    def dispatch_settings(
        self,
        intent: SettingsIntent | None = None,
        config_store: ProviderConfigStore | None = None,
    ) -> SettingsOptionsOutcome | SettingsUpdatedOutcome | CommandErrorOutcome:
        """Inspect or change settings."""
        setting = intent.setting if intent is not None else None
        value = intent.value if intent is not None else None

        if setting is None:
            options = (
                SettingOption("hide_thinking", "Hide thinking blocks", str(getattr(self, "_hide_thinking", False)), "toggle"),
                SettingOption("reasoning_effort", "Reasoning effort", str(getattr(self, "_reasoning_effort", "low")), "choice", ("none", "low", "medium", "high")),
                SettingOption("model", "Active model", str(self._model or "default"), "text"),
            )
            return SettingsOptionsOutcome(settings=options)

        if value is None:
            return CommandErrorOutcome(command="settings", error=f"Value required to update setting '{setting}'")

        if setting in {"hide_thinking", "hide-thinking"}:
            new_val = value.lower() in {"true", "1", "yes", "on"}
            object.__setattr__(self, "_hide_thinking", new_val)
            return SettingsUpdatedOutcome(setting="hide_thinking", value=str(new_val))

        if setting in {"reasoning_effort", "reasoning", "reasoning-effort"}:
            if value not in {"none", "low", "medium", "high"}:
                return CommandErrorOutcome(command="settings", error=f"Invalid reasoning effort value: {value}")
            object.__setattr__(self, "_reasoning_effort", value)
            return SettingsUpdatedOutcome(setting="reasoning_effort", value=value)

        if setting == "model":
            self._model = value
            return SettingsUpdatedOutcome(setting="model", value=value)

        return CommandErrorOutcome(command="settings", error=f"Unknown setting: '{setting}'")

    def dispatch_logout(
        self,
        intent: LogoutIntent | None = None,
        config_store: ProviderConfigStore | None = None,
    ) -> LogoutOptionsOutcome | LogoutSuccessOutcome | CommandErrorOutcome:
        """List providers to remove or remove specified provider."""
        target = intent.target if intent is not None else None
        store_configs: tuple[ProviderConfig, ...] = ()
        if config_store is not None:
            try:
                store_configs = config_store.load_all()
            except OSError:
                store_configs = ()

        if not store_configs:
            return CommandErrorOutcome(command="logout", error="No saved providers to remove.")

        if target is not None:
            matching = [
                c for c in store_configs
                if provider_id(c) == target
                or c.name == target
                or c.model == target
                or target in c.models
            ]
            if not matching:
                return CommandErrorOutcome(command="logout", error=f"Unknown provider '{target}'")
            target_config = matching[0]
            if config_store is not None:
                try:
                    config_store.delete(target_config)
                except OSError as error:
                    return CommandErrorOutcome(command="logout", error=str(error))

            remaining = [c for c in store_configs if provider_id(c) != provider_id(target_config)]
            next_active = remaining[0].name if remaining else None
            next_config = remaining[0] if remaining else None
            return LogoutSuccessOutcome(
                removed_provider_name=target_config.name,
                active_provider_name=next_active,
                active_config=next_config,
            )

        token = self._id_factory()
        options = tuple(
            (str(idx), config.name)
            for idx, config in enumerate(store_configs, 1)
        )
        token_map = {str(idx): config for idx, config in enumerate(store_configs, 1)}
        self._continuation_tokens[token] = {
            "type": "logout",
            "map": token_map,
            "configs": store_configs,
            "config_store": config_store,
        }
        return LogoutOptionsOutcome(
            options=options,
            continuation_token=token,
        )

    def dispatch_continuation_response(
        self,
        intent: ContinuationResponseIntent,
    ) -> CommandOutcome:
        """Process response for a single-use continuation token."""
        token_data = self._continuation_tokens.pop(intent.continuation_token, None)
        if token_data is None:
            return CommandErrorOutcome(
                command="continuation",
                error=f"Continuation token '{intent.continuation_token}' is invalid, expired, or already used.",
            )

        flow_type = token_data.get("type")
        if flow_type == "model":
            resp_str = str(intent.response).strip()
            choices = cast(tuple[SavedModel, ...], token_data["choices"])
            try:
                choice = select_saved_model(resp_str, choices)
            except Exception as error:
                return CommandErrorOutcome(command="model", error=str(error))

            self._model = choice.model
            options = tuple(
                ModelOption(
                    option_id=str(idx),
                    label=c.label,
                    provider_name=c.config.name,
                    model_name=c.model,
                    active=(c.model == choice.model),
                )
                for idx, c in enumerate(choices, 1)
            )
            return ModelOptionsOutcome(
                options=options,
                current_model=choice.model,
                updated=True,
            )

        if flow_type == "logout":
            resp_str = str(intent.response).strip()
            token_map = cast(dict[str, ProviderConfig], token_data["map"])
            config_choice = token_map.get(resp_str)
            if config_choice is None:
                return CommandErrorOutcome(command="logout", error=f"Invalid provider choice '{resp_str}'")

            config_store = cast("ProviderConfigStore | None", token_data.get("config_store"))
            if config_store is not None:
                try:
                    config_store.delete(config_choice)
                except OSError as error:
                    return CommandErrorOutcome(command="logout", error=str(error))

            remaining = [c for c in token_map.values() if c.name != config_choice.name]
            next_active = remaining[0].name if remaining else None
            next_config = remaining[0] if remaining else None
            return LogoutSuccessOutcome(
                removed_provider_name=config_choice.name,
                active_provider_name=next_active,
                active_config=next_config,
            )

        if flow_type == "provider_step":
            step = token_data.get("step")
            data = cast(dict[str, Any], token_data.get("data", {}))
            config_store = cast("ProviderConfigStore | None", token_data.get("config_store"))
            resp_str = str(intent.response).strip()

            if step == "provider_type":
                norm = resp_str.casefold()
                if norm in {"1", "openai-compatible", "openai"}:
                    p_type = "openai-compatible"
                    next_step = "base_url"
                    prompt = "Enter base URL:"
                    is_sec = False
                elif norm in {"2", "custom"}:
                    p_type = "custom"
                    next_step = "custom_name"
                    prompt = "Enter custom provider name:"
                    is_sec = False
                elif norm in {"3", "github-copilot", "copilot"}:
                    p_type = "github-copilot"
                    next_step = "copilot_token"
                    prompt = "Enter Copilot token:"
                    is_sec = True
                else:
                    return CommandErrorOutcome(
                        command="provider",
                        error=f"Invalid provider choice '{resp_str}'",
                    )
                data["provider_type"] = p_type
                new_token = self._id_factory()
                self._continuation_tokens[new_token] = {
                    "type": "provider_step",
                    "step": next_step,
                    "data": data,
                    "config_store": config_store,
                }
                return ProviderSetupStepOutcome(
                    step=next_step,
                    prompt=prompt,
                    is_secret=is_sec,
                    continuation_token=new_token,
                )

            if step == "custom_name":
                data["name"] = resp_str or "custom"
                new_token = self._id_factory()
                self._continuation_tokens[new_token] = {
                    "type": "provider_step",
                    "step": "model",
                    "data": data,
                    "config_store": config_store,
                }
                return ProviderSetupStepOutcome(
                    step="model",
                    prompt="Enter model name:",
                    is_secret=False,
                    continuation_token=new_token,
                )

            if step == "base_url":
                data["base_url"] = resp_str
                new_token = self._id_factory()
                self._continuation_tokens[new_token] = {
                    "type": "provider_step",
                    "step": "api_key",
                    "data": data,
                    "config_store": config_store,
                }
                return ProviderSetupStepOutcome(
                    step="api_key",
                    prompt="Enter API key:",
                    is_secret=True,
                    continuation_token=new_token,
                )

            if step == "api_key":
                data["api_key"] = resp_str
                new_token = self._id_factory()
                self._continuation_tokens[new_token] = {
                    "type": "provider_step",
                    "step": "model",
                    "data": data,
                    "config_store": config_store,
                }
                return ProviderSetupStepOutcome(
                    step="model",
                    prompt="Enter model name:",
                    is_secret=False,
                    continuation_token=new_token,
                )

            if step == "copilot_token":
                data["copilot_token"] = resp_str
                provider_type = "github-copilot"
                name = "github-copilot"
                model_str = "gpt-4o"
                config = ProviderConfig(
                    name=name,
                    provider_type=provider_type,
                    model=model_str,
                    models=(model_str, "gpt-4o-mini"),
                    copilot_token=resp_str,
                )
                if config_store is not None:
                    try:
                        config_store.save(config)
                    except OSError as err:
                        return CommandErrorOutcome(command="provider", error=str(err))
                self._model = model_str
                return ProviderSuccessOutcome(
                    provider_name=name,
                    model_name=model_str,
                    config=config,
                )

            if step == "model":
                model_str = resp_str
                if not model_str:
                    return CommandErrorOutcome(
                        command="provider",
                        error="Model name is required.",
                    )
                provider_type = data.get("provider_type", "openai-compatible")
                name = data.get("name") or provider_type
                config = ProviderConfig(
                    name=name,
                    provider_type=provider_type,
                    model=model_str,
                    models=(model_str,),
                    base_url=data.get("base_url"),
                    api_key=data.get("api_key"),
                )
                if config_store is not None:
                    try:
                        config_store.save(config)
                    except OSError as err:
                        return CommandErrorOutcome(command="provider", error=str(err))
                self._model = model_str
                return ProviderSuccessOutcome(
                    provider_name=name,
                    model_name=model_str,
                    config=config,
                )

        return CommandErrorOutcome(command="continuation", error=f"Unknown flow type '{flow_type}'")

    def dispatch_shell(
        self,
        intent: ShellIntent,
        execution_context: ToolExecutionContext | None = None,
    ) -> ShellResultOutcome | ShellErrorOutcome:
        """Execute a direct visible or hidden shell command."""
        command = intent.command.strip()
        if not command:
            return ShellErrorOutcome(command=intent.command, error="bash command is required")

        if self._executor is None:
            return ShellErrorOutcome(command=command, error="No tool executor configured.")

        registered_tools = getattr(self._executor, "tools", ())
        if not any(getattr(tool, "name", None) == "bash" for tool in registered_tools):
            return ShellErrorOutcome(command=command, error="bash tool is not registered")

        if self._enabled_tools is not None and "bash" not in self._enabled_tools:
            return ShellErrorOutcome(command=command, error="tool 'bash' is disabled")

        op_id = self._id_factory()
        self._session._emit(
            ToolStartedEvent(
                session_id=self.session_id,
                run_id=self.run_id,
                turn_id=None,
                operation_id=op_id,
                tool_name="bash",
                arguments={"command": command},
                call_id=None,
                source="shell",
            )
        )

        orig_on_output = (
            execution_context.on_output if execution_context is not None else None
        )

        def _handle_shell_output(stream_name: str, chunk: str) -> None:
            self._session._emit(
                ToolOutputEvent(
                    session_id=self.session_id,
                    run_id=self.run_id,
                    turn_id=None,
                    operation_id=op_id,
                    stream=stream_name,
                    chunk=chunk,
                )
            )
            if orig_on_output is not None:
                orig_on_output(stream_name, chunk)

        active_context = ToolExecutionContext(on_output=_handle_shell_output)
        if execution_context is not None and execution_context.cancelled:
            active_context.cancel()

        try:
            if hasattr(self._executor, "invoke_with_context"):
                output = str(
                    getattr(self._executor, "invoke_with_context")(
                        "bash",
                        {"command": command},
                        active_context,
                    )
                )
            else:
                output = str(self._executor.invoke("bash", {"command": command}))
        except Exception as caught:
            outcome: Literal["success", "error", "cancelled"] = (
                "cancelled" if active_context.cancelled else "error"
            )
            self._session._emit(
                ToolFinishedEvent(
                    session_id=self.session_id,
                    run_id=self.run_id,
                    turn_id=None,
                    operation_id=op_id,
                    tool_name="bash",
                    outcome=outcome,
                    error=str(caught),
                    call_id=None,
                    source="shell",
                )
            )
            return ShellErrorOutcome(command=command, error=str(caught))

        outcome_success: Literal["success", "error", "cancelled"] = (
            "cancelled" if active_context.cancelled else "success"
        )
        self._session._emit(
            ToolFinishedEvent(
                session_id=self.session_id,
                run_id=self.run_id,
                turn_id=None,
                operation_id=op_id,
                tool_name="bash",
                outcome=outcome_success,
                result=output if outcome_success == "success" else None,
                error="command cancelled" if outcome_success != "success" else None,
                call_id=None,
                source="shell",
            )
        )

        if intent.hidden:
            return ShellResultOutcome(
                command=command,
                output=output,
                exit_code=0,
                hidden=True,
                turn_result=None,
            )

        task = f"Shell command `{command}` output:\n{output}"
        turn_result = self._session.prompt(task)
        return ShellResultOutcome(
            command=command,
            output=output,
            exit_code=0,
            hidden=False,
            turn_result=turn_result,
        )

    def cancel(self) -> bool:
        """Request cancellation of the active prompt, if one is running."""
        return self._session.cancel()

    def _switch_to_session(
        self,
        action: Literal["resume"],
        record: SessionRecord,
    ) -> SessionTransitionOutcome:
        old_session_id = self.session_id
        self._context = AgentContext(messages=list(record.messages))
        if self._resources is not None:
            apply_resource_prompt(self._context, self._resources)

        self._session = CodingSession(
            provider=self.provider,
            session_store=self.session_store,
            session_id=record.session_id,
            run_id=self.run_id,
            context=self._context,
            executor=self._executor,
            model=self._model,
            resources=self._resources,
            on_event=self._session._on_event,
            on_tool_output=self._session._on_tool_output,
            clock=self._session._clock,
            id_factory=self._session._id_factory,
            trace_sink=self._trace_sink,
            trace_provider=self._trace_provider,
            trace_utc_clock=self._trace_utc_clock,
            limits=self._limits,
            journal_sink=self._journal_sink,
            event_utc_clock=self._event_utc_clock,
            event_sequence_start=self._session._event_sequence,
        )

        return SessionTransitionOutcome(
            action=action,
            session_id=record.session_id,
            parent_id=record.parent_id,
            name=record.name,
            record=record,
            messages=self.messages,
        )

    def _execute_tools_command(self) -> ToolsOutcome:
        tools: list[ToolStatus] = []
        underlying = getattr(self._executor, "_executor", self._executor)
        if isinstance(underlying, ExtensionRegistry):
            all_registered = underlying.tools
        elif hasattr(underlying, "tools"):
            all_registered = getattr(underlying, "tools")
        else:
            all_registered = ()

        if self._enabled_tools is not None:
            enabled_set = set(self._enabled_tools)
        elif hasattr(self._executor, "tools"):
            enabled_set = {t.name for t in getattr(self._executor, "tools")}
        else:
            enabled_set = {t.name for t in all_registered}

        for tool in all_registered:
            is_enabled = tool.name in enabled_set
            tools.append(
                ToolStatus(
                    name=tool.name,
                    description=tool.description,
                    registered=True,
                    enabled=is_enabled,
                )
            )
        return ToolsOutcome(tools=tuple(tools))

    def _execute_session_command(self) -> SessionInfoOutcome:
        try:
            record = self.session_store.load(self.session_id)
        except (OSError, SessionStoreError):
            record = None

        msgs = conversation_messages_without_resource_prompt(
            self._context.messages,
            self._resources,
        )
        msg_count = len(msgs)
        user_count = sum(1 for m in msgs if m.role == "user")
        return SessionInfoOutcome(
            session_id=self.session_id,
            message_count=msg_count,
            interaction_count=user_count,
            usage=None,
            record=record,
        )

    def _execute_reasoning_command(self, argument: str) -> ReasoningOutcome | CommandErrorOutcome:
        if not self._reasoning_choices:
            return ReasoningOutcome(supported=False, current=None, choices=())
        if argument:
            arg_clean = argument.strip().lower()
            if arg_clean in self._reasoning_choices:
                self._reasoning_effort = arg_clean
                if hasattr(self.provider, "config"):
                    try:
                        setattr(self.provider.config, "reasoning_effort", arg_clean)
                    except (AttributeError, TypeError):
                        pass
                return ReasoningOutcome(
                    supported=True,
                    current=self._reasoning_effort,
                    choices=self._reasoning_choices,
                    updated=True,
                )
            return CommandErrorOutcome(
                command="reasoning",
                error=f"Invalid reasoning effort '{argument}'. Choices: {', '.join(self._reasoning_choices)}",
            )

        current_effort = self._reasoning_effort
        if current_effort in self._reasoning_choices:
            current_idx = self._reasoning_choices.index(current_effort)
            next_idx = (current_idx + 1) % len(self._reasoning_choices)
            new_effort = self._reasoning_choices[next_idx]
        else:
            new_effort = self._reasoning_choices[0]

        self._reasoning_effort = new_effort
        if hasattr(self.provider, "config"):
            try:
                setattr(self.provider.config, "reasoning_effort", new_effort)
            except (AttributeError, TypeError):
                pass

        return ReasoningOutcome(
            supported=True,
            current=self._reasoning_effort,
            choices=self._reasoning_choices,
            updated=True,
        )

    def _get_registered_skill_names(self) -> tuple[str, ...]:
        underlying = getattr(self._executor, "_executor", self._executor)
        if isinstance(underlying, ExtensionRegistry):
            return underlying.skills
        if hasattr(underlying, "skills"):
            skills_val = getattr(underlying, "skills")
            if isinstance(skills_val, tuple):
                return skills_val
        return ()

    def _get_available_skill_names(self) -> tuple[str, ...]:
        if self._resources is not None:
            return tuple(s.name for s in self._resources.skills)
        return ()

    def _get_all_skills(self) -> tuple[SkillStatus, ...]:
        skills: list[SkillStatus] = []
        loaded_names: set[str] = set()
        if self._resources is not None:
            for skill in self._resources.skills:
                skills.append(
                    SkillStatus(
                        name=skill.name,
                        status="available",
                        path=str(skill.path) if skill.path is not None else None,
                    )
                )
                loaded_names.add(skill.name)

        registered = self._get_registered_skill_names()
        for name in registered:
            if name not in loaded_names:
                skills.append(SkillStatus(name=name, status="registered"))

        return tuple(skills)
