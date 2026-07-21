"""Host-neutral session controller for prompt and command dispatch."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
import time
from typing import Literal, TypeAlias
from uuid import uuid4

from peon.agent import (
    AgentContext,
    AgentMessage,
    ModelProvider,
    ToolExecutor,
    Usage,
)
from peon.agent.tracing import TraceSink
from peon.extensions import ExtensionRegistry

from .coding_session import (
    CodingSession,
    EventHandler,
    MessageEvent,
    SessionEvent,
    TurnFinishedEvent,
    TurnResult,
    TurnStartedEvent,
)
from .commands import (
    DEFAULT_COMMAND_CATALOG,
    CommandDefinition,
)
from .resources import (
    ResourceInventory,
    conversation_messages_without_resource_prompt,
    load_skill_into_context,
)
from .sessions import SessionRecord, SessionStore, SessionStoreError


@dataclass(frozen=True, slots=True)
class PromptIntent:
    """Typed prompt request for dispatch through the session controller."""

    text: str
    preserve_whitespace: bool = False


@dataclass(frozen=True, slots=True)
class CommandIntent:
    """Typed slash command request for dispatch through the session controller."""

    command: str


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
    path: str | None = None
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
    | CommandErrorOutcome
)


class SessionController:
    """Dispatch typed prompt and command intents through a host-neutral session boundary.

    Composes :class:`CodingSession` rather than duplicating the agent loop.
    Every host (one-shot CLI, print, JSONL, embedded, Textual, prompt-toolkit)
    dispatches prompts and commands through this controller to get equivalent
    events, results, persistence, cancellation, resources, and tool behavior.
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

    def dispatch(self, intent: PromptIntent) -> TurnResult:
        """Dispatch one typed prompt intent and return a structured outcome."""
        return self._session.prompt(
            intent.text,
            preserve_task_whitespace=intent.preserve_whitespace,
        )

    def dispatch_command(self, intent: CommandIntent) -> CommandOutcome:
        """Dispatch one informational command intent and return a typed outcome."""
        raw_cmd = intent.command.strip()
        name = raw_cmd.split(maxsplit=1)[0]
        normalized_name = name.casefold()

        # Handle skill selection (/skill:<name>)
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

        return CommandErrorOutcome(command=raw_cmd, error=f"Command '{cmd_id}' is not an informational command.")

    def cancel(self) -> bool:
        """Request cancellation of the active prompt, if one is running."""
        return self._session.cancel()

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
        if isinstance(self._executor, ExtensionRegistry):
            return self._executor.skills
        if hasattr(self._executor, "skills"):
            skills_val = getattr(self._executor, "skills")
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
