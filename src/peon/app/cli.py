"""Command boundary for running a minimal Peon task."""

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, TextIO

from peon.agent import AgentContext, AgentError, ModelProvider, ToolCall, run_task
from peon.ai import (
    CustomProvider,
    CustomRequestFields,
    CustomResponseFields,
    GitHubCopilotProvider,
    OpenAICompatibleProvider,
    ProviderError,
)
from peon.extensions import (
    ExtensionRegistry,
    register_filesystem_tools,
    register_sample_tools,
)

from .coding_session import CodingSession, MessageEvent, SessionEvent
from .sessions import SessionStore
from .resources import ResourceInventory, ResourceLoader, apply_resource_prompt


REASONING_EFFORTS = ("none", "low", "medium", "high")
PROVIDER_REASONING_CAPABILITIES = {
    "openai-compatible": REASONING_EFFORTS,
    "custom": REASONING_EFFORTS,
}


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    name: str
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    copilot_token: str | None = None
    models: tuple[str, ...] = ()
    provider_type: str | None = None
    reasoning_effort_field: str = "reasoningEffort"
    reasoning_effort: str | None = "low"
    temperature_field: str = "temperature"
    temperature: float | None = 1
    max_response_tokens_field: str = "maxResponseTokens"
    max_response_tokens: int | None = 4096
    max_output_tokens_field: str = "maxOutputTokens"
    max_output_tokens: int | None = None
    max_tokens_field: str = "maxTokens"
    max_tokens: int | None = None
    response_format_field: str = "responseFormat"
    response_format: str | None = "text"
    response_content_field: str = "completion"
    response_thinking_field: str = "thinking"
    tool_prompt_role: str = "developer"
    supports_tools: bool | None = None
    supports_stream: bool = False
    supports_chat_completions: bool = True

    def __post_init__(self) -> None:
        if self.supports_tools is None:
            provider_type = self.provider_type or self.name
            object.__setattr__(self, "supports_tools", provider_type != "custom")


def reasoning_effort_choices(config: ProviderConfig) -> tuple[str, ...]:
    provider_type = config.provider_type or config.name
    return PROVIDER_REASONING_CAPABILITIES.get(provider_type, ())


def cycle_reasoning_effort(config: ProviderConfig, direction: int = 1) -> str:
    choices = reasoning_effort_choices(config)
    if not choices:
        raise CommandError("reasoning effort is not supported by this provider")
    current = config.reasoning_effort or "none"
    try:
        index = choices.index(current)
    except ValueError:
        index = -1 if direction > 0 else 0
    return choices[(index + direction) % len(choices)]


@dataclass(frozen=True, slots=True)
class ProviderSettingSpec:
    key: str
    label: str
    field_name: str
    value_kind: Literal["text", "secret", "integer", "temperature", "choice", "toggle"]
    choices: tuple[str, ...] = ()


PROFILE_SETTING_SPECS = (
    ProviderSettingSpec("name", "Name", "name", "text"),
)
CONFIG_SETTING_SPECS = (
    ProviderSettingSpec("base-url", "Base URL", "base_url", "text"),
    ProviderSettingSpec("api-key", "API key", "api_key", "secret"),
    ProviderSettingSpec(
        "max-completion-tokens",
        "Max completion tokens",
        "max_response_tokens",
        "integer",
    ),
    ProviderSettingSpec(
        "max-output-tokens", "Max output tokens", "max_output_tokens", "integer"
    ),
    ProviderSettingSpec("max-tokens", "Max tokens", "max_tokens", "integer"),
    ProviderSettingSpec(
        "reasoning",
        "Reasoning",
        "reasoning_effort",
        "choice",
        ("none", "low", "medium", "high"),
    ),
    ProviderSettingSpec("supports-tools", "Supports tools", "supports_tools", "toggle"),
    ProviderSettingSpec(
        "tool-prompt-role",
        "Tool prompt role",
        "tool_prompt_role",
        "choice",
        ("developer", "system"),
    ),
    ProviderSettingSpec(
        "supports-stream", "Supports stream", "supports_stream", "toggle"
    ),
    ProviderSettingSpec(
        "supports-chat-completions",
        "Supports /chat/completions",
        "supports_chat_completions",
        "toggle",
    ),
    ProviderSettingSpec("temperature", "Temperature", "temperature", "temperature"),
    ProviderSettingSpec("response-format", "Response format", "response_format", "text"),
)


def provider_config_setting_specs(
    config: ProviderConfig,
) -> tuple[ProviderSettingSpec, ...]:
    if reasoning_effort_choices(config):
        return CONFIG_SETTING_SPECS
    return tuple(spec for spec in CONFIG_SETTING_SPECS if spec.key != "reasoning")


REQUEST_FIELD_SETTING_SPECS = (
    ProviderSettingSpec(
        "reasoning-effort-field",
        "reasoning_effort",
        "reasoning_effort_field",
        "text",
    ),
    ProviderSettingSpec("temperature-field", "temperature", "temperature_field", "text"),
    ProviderSettingSpec(
        "max-completion-tokens-field",
        "max_completion_tokens",
        "max_response_tokens_field",
        "text",
    ),
    ProviderSettingSpec(
        "max-output-tokens-field",
        "max_output_tokens",
        "max_output_tokens_field",
        "text",
    ),
    ProviderSettingSpec(
        "max-tokens-field", "max_tokens", "max_tokens_field", "text"
    ),
    ProviderSettingSpec(
        "response-format-field",
        "response_format",
        "response_format_field",
        "text",
    ),
)
RESPONSE_FIELD_SETTING_SPECS = (
    ProviderSettingSpec(
        "response-content-field",
        "choices[0].message.content",
        "response_content_field",
        "text",
    ),
    ProviderSettingSpec(
        "response-thinking-field",
        "thinking",
        "response_thinking_field",
        "text",
    ),
)
PROVIDER_SETTING_SPECS = {
    spec.key: spec
    for spec in (
        *PROFILE_SETTING_SPECS,
        *CONFIG_SETTING_SPECS,
        *REQUEST_FIELD_SETTING_SPECS,
        *RESPONSE_FIELD_SETTING_SPECS,
    )
}


def update_provider_setting(
    config: ProviderConfig,
    setting: str,
    value: str,
) -> ProviderConfig:
    aliases = {
        "reasoning-effort": "reasoning",
        "max-response-tokens": "max-completion-tokens",
        "max-response-tokens-field": "max-completion-tokens-field",
    }
    spec = PROVIDER_SETTING_SPECS.get(aliases.get(setting, setting))
    if spec is None:
        raise CommandError(f"unknown provider setting '{setting}'")
    field_name = spec.field_name
    if spec.value_kind in {"text", "secret"}:
        if field_name == "api_key" and value.lower() in {"", "none"}:
            return replace(config, api_key=None)
        if not value:
            raise CommandError(f"{setting} cannot be blank")
        if field_name == "name":
            return replace(
                config,
                name=value,
                provider_type=config.provider_type or config.name,
            )
        if field_name == "base_url":
            return replace(config, base_url=value)
        if field_name == "api_key":
            return replace(config, api_key=value)
        if field_name == "reasoning_effort_field":
            return replace(config, reasoning_effort_field=value)
        if field_name == "temperature_field":
            return replace(config, temperature_field=value)
        if field_name == "max_response_tokens_field":
            return replace(config, max_response_tokens_field=value)
        if field_name == "max_output_tokens_field":
            return replace(config, max_output_tokens_field=value)
        if field_name == "max_tokens_field":
            return replace(config, max_tokens_field=value)
        if field_name == "response_format_field":
            return replace(config, response_format_field=value)
        if field_name == "response_content_field":
            return replace(config, response_content_field=value)
        if field_name == "response_thinking_field":
            return replace(config, response_thinking_field=value)
        return replace(config, response_format=value)
    if spec.value_kind == "choice":
        lowered_value = value.lower()
        if lowered_value not in spec.choices:
            raise CommandError(f"{setting} must be one of: {', '.join(spec.choices)}")
        if spec.key == "reasoning" and not reasoning_effort_choices(config):
            raise CommandError("reasoning effort is not supported by this provider")
        if field_name == "tool_prompt_role":
            return replace(config, tool_prompt_role=lowered_value)
        return replace(
            config,
            reasoning_effort=None if lowered_value == "none" else lowered_value,
        )
    if spec.value_kind == "toggle":
        lowered_value = value.lower()
        if lowered_value not in {"true", "false"}:
            raise CommandError(f"{setting} must be true or false")
        enabled = lowered_value == "true"
        if field_name == "supports_tools":
            return replace(config, supports_tools=enabled)
        if field_name == "supports_stream":
            return replace(config, supports_stream=enabled)
        return replace(config, supports_chat_completions=enabled)
    if spec.value_kind == "temperature":
        try:
            parsed_value = float(value)
        except ValueError as error:
            raise CommandError("temperature must be a number") from error
        if not 0 <= parsed_value <= 1:
            raise CommandError("temperature must be between 0 and 1")
        return replace(config, temperature=parsed_value)
    if value.lower() in {"", "none"}:
        if field_name == "max_response_tokens":
            return replace(config, max_response_tokens=None)
        if field_name == "max_output_tokens":
            return replace(config, max_output_tokens=None)
        return replace(config, max_tokens=None)
    try:
        parsed_value = int(value)
    except ValueError as error:
        raise CommandError(f"{spec.label.lower()} must be an integer") from error
    if parsed_value < 1:
        raise CommandError(f"{spec.label.lower()} must be at least 1")
    if field_name == "max_response_tokens":
        return replace(config, max_response_tokens=parsed_value)
    if field_name == "max_output_tokens":
        return replace(config, max_output_tokens=parsed_value)
    return replace(config, max_tokens=parsed_value)


ProviderFactory = Callable[[ProviderConfig], ModelProvider]
InteractionMode = Literal["non-interactive", "minimal", "fullscreen", "webapp"]


class CommandError(Exception):
    """An operator-facing command boundary error."""


@dataclass(frozen=True, slots=True)
class SavedModel:
    config: ProviderConfig
    model: str

    @property
    def label(self) -> str:
        return f"{self.model} [{self.config.name}]"


def saved_model_choices(
    configs: Sequence[ProviderConfig],
) -> tuple[SavedModel, ...]:
    return tuple(
        SavedModel(config=config, model=model)
        for config in configs
        for model in config.models
    )


def select_saved_model(
    selection: str,
    choices: tuple[SavedModel, ...],
) -> SavedModel:
    if selection.isdigit():
        index = int(selection) - 1
        if 0 <= index < len(choices):
            return choices[index]
    matches = tuple(choice for choice in choices if choice.model == selection)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise CommandError("select model by number when model IDs repeat")
    raise CommandError("select a model by number or exact model ID")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="peon",
        description="Run a task through the Peon agent core.",
    )
    parser.add_argument("task", nargs="*", help="Task to send to the agent")
    parser.add_argument("--provider", help="Provider adapter name")
    parser.add_argument("--provider-name", help="Custom display name for a custom provider")
    parser.add_argument("--model", help="Provider model name")
    parser.add_argument("--base-url", help="OpenAI-compatible provider base URL")
    parser.add_argument("--api-key", help="OpenAI-compatible provider API key")
    parser.add_argument("--copilot-token", help="GitHub Copilot login token")
    parser.add_argument(
        "--reasoning-effort-field",
        default="reasoningEffort",
        help="Custom provider request field for reasoning effort",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=REASONING_EFFORTS,
        default="low",
        help="Custom provider reasoning effort value",
    )
    parser.add_argument(
        "--tool-prompt-role",
        choices=("developer", "system"),
        default="developer",
        help="Role used for fallback tool instructions",
    )
    parser.add_argument(
        "--no-context-files",
        action="store_true",
        help="Disable discovered context files",
    )
    parser.add_argument(
        "--no-skills",
        action="store_true",
        help="Disable discovered skills",
    )
    parser.add_argument(
        "--no-project-context",
        action="store_true",
        help="Ignore discovered project skills and context files",
    )
    parser.add_argument(
        "--skill-path",
        action="append",
        type=Path,
        default=[],
        help="Load an explicit skill directory or SKILL.md path",
    )
    parser.add_argument(
        "--context-file",
        action="append",
        type=Path,
        default=[],
        help="Load an explicit context file",
    )
    parser.add_argument(
        "--system-prompt",
        help="Replace discovered system prompt text",
    )
    parser.add_argument(
        "--system-prompt-file",
        type=Path,
        help="Replace discovered system prompt with a file",
    )
    parser.add_argument(
        "--append-system-prompt",
        action="append",
        default=[],
        help="Append literal system prompt text",
    )
    parser.add_argument(
        "--append-system-prompt-file",
        action="append",
        type=Path,
        default=[],
        help="Append system prompt text from a file",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Start an interactive session with in-session provider setup",
    )
    parser.add_argument(
        "-p",
        "--print",
        dest="print_mode",
        action="store_true",
        help="Run one prompt and print the final assistant response",
    )
    parser.add_argument(
        "--events",
        "--jsonl",
        "--json",
        dest="event_mode",
        action="store_true",
        help="Emit one normalized JSON event per line in print mode",
    )
    parser.add_argument(
        "-c",
        "--continue",
        dest="continue_session",
        action="store_true",
        help="Continue the most recent session for the current directory",
    )
    parser.add_argument(
        "--no-session",
        dest="no_session",
        action="store_true",
        help="Keep the conversation in memory without saving a session",
    )
    parser.add_argument(
        "--session",
        dest="session_target",
        help="Open an exact current-directory session ID or unique name",
    )
    parser.add_argument(
        "--session-name",
        dest="session_name",
        help="Name a newly created interactive session",
    )
    parser.add_argument(
        "--mode",
        choices=("non-interactive", "minimal", "fullscreen", "webapp"),
        help="Interaction level; defaults to non-interactive with a task, minimal without one",
    )
    parser.add_argument(
        "--user-top-blank-lines",
        type=int,
        default=1,
        help="Blank rows above each user message in the TUI",
    )
    parser.add_argument(
        "--user-bottom-blank-lines",
        type=int,
        default=1,
        help="Blank rows below each user message in the TUI",
    )
    parser.add_argument(
        "--message-left-padding",
        type=int,
        default=1,
        help="Visual left padding for user and assistant messages in the TUI",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    provider_factory: ProviderFactory | None = None,
    tui_runner: Callable[..., int] | None = None,
    input: TextIO | None = None,
    output: TextIO | None = None,
    error: TextIO | None = None,
    registry: ExtensionRegistry | None = None,
    session_store: SessionStore | None = None,
) -> int:
    input_stream = input or sys.stdin
    output = output or sys.stdout
    error = error or sys.stderr
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if args.continue_session and args.no_session:
            raise CommandError("--continue and --no-session cannot be combined")
        if args.no_session and (args.session_target or args.session_name):
            raise CommandError(
                "--no-session cannot be combined with --session or --session-name"
            )
        if args.continue_session and args.session_target:
            raise CommandError("--continue and --session cannot be combined")
        if args.session_target and args.session_name:
            raise CommandError("--session and --session-name cannot be combined")
        if args.continue_session and args.session_name:
            raise CommandError("--continue and --session-name cannot be combined")
        task = " ".join(args.task).strip()
        if args.print_mode:
            if args.tui or args.mode is not None:
                raise CommandError("--print cannot be combined with interactive mode")
            if not task:
                task = _read_piped_input(input_stream)
            else:
                piped_input = _read_piped_input(input_stream)
                if piped_input:
                    task = f"{task}\n\n{piped_input}"
            if not task:
                raise CommandError("task is required")
            if args.event_mode:
                return _run_print_mode(
                    task,
                    args=args,
                    provider_factory=provider_factory,
                    output=output,
                    error=error,
                    registry=registry,
                    session_store=session_store,
                    event_mode=True,
                )
            return _run_print_mode(
                task,
                args=args,
                provider_factory=provider_factory,
                output=output,
                error=error,
                registry=registry,
                session_store=session_store,
                event_mode=False,
            )
        if args.event_mode:
            raise CommandError("--events requires --print")
        mode: InteractionMode = args.mode or (
            "minimal" if args.tui or not task else "non-interactive"
        )
        if mode != "minimal" and (
            args.continue_session
            or args.no_session
            or args.session_target
            or args.session_name
        ):
            raise CommandError(
                "session lifecycle options require interactive mode"
            )
        if mode == "non-interactive":
            if not task:
                raise CommandError("task is required")
        elif mode == "minimal":
            if task:
                raise CommandError("minimal mode does not accept a task argument")
            from .tui import run_tui

            return (tui_runner or run_tui)(
                provider_factory=provider_factory,
                output=output,
                error=error,
                user_top_blank_lines=args.user_top_blank_lines,
                user_bottom_blank_lines=args.user_bottom_blank_lines,
                message_left_padding=args.message_left_padding,
                continue_session=args.continue_session,
                no_session=args.no_session,
                session_target=args.session_target,
                session_name=args.session_name,
                resources=_load_resources(args),
            )
        else:
            raise CommandError(f"{mode} mode is not available yet")
        if not args.provider:
            raise CommandError("provider is not configured")

        config = ProviderConfig(
            name=args.provider_name or args.provider,
            provider_type=args.provider if args.provider == "custom" else None,
            model=args.model,
            base_url=args.base_url,
            api_key=args.api_key,
            copilot_token=args.copilot_token,
            reasoning_effort_field=args.reasoning_effort_field,
            reasoning_effort=(
                None if args.reasoning_effort == "none" else args.reasoning_effort
            ),
            tool_prompt_role=args.tool_prompt_role,
        )
        provider = (provider_factory or create_provider)(config)
        context = AgentContext()
        apply_resource_prompt(context, _load_resources(args))
        response = run_task(task, provider, context=context, model=config.model)
        if isinstance(response, ToolCall):
            raise CommandError(
                f"provider requested tool '{response.name}', but tool execution "
                "is not configured"
            )
    except (AgentError, CommandError, ProviderError, ValueError) as caught:
        print(f"{parser.prog}: {caught}", file=error)
        return 1

    print(response, file=output)
    return 0


def _read_piped_input(input_stream: TextIO) -> str:
    try:
        if input_stream.isatty():
            return ""
    except (AttributeError, OSError):
        pass
    try:
        return input_stream.read()
    except (OSError, ValueError):
        return ""


def _run_print_mode(
    task: str,
    *,
    args: argparse.Namespace,
    provider_factory: ProviderFactory | None,
    output: TextIO,
    error: TextIO,
    registry: ExtensionRegistry | None,
    session_store: SessionStore | None,
    event_mode: bool,
) -> int:
    from .sessions import (
        JsonlSessionStore,
        MemorySessionStore,
        SessionStoreError,
        create_session,
        select_session,
    )

    events = _EventWriter(output) if event_mode else None
    explicit_durable_session = bool(
        args.continue_session or args.session_target or args.session_name
    )
    active_store: SessionStore
    if args.no_session or not explicit_durable_session:
        active_store = MemorySessionStore()
    elif session_store is not None:
        active_store = session_store
    else:
        active_store = JsonlSessionStore()

    session_id = ""
    session_started = False
    try:
        if args.session_target:
            selected = select_session(active_store, args.session_target)
            context = AgentContext(messages=list(selected.messages))
            session_id = selected.session_id
        elif args.continue_session:
            latest = active_store.load_latest()
            if latest is None:
                created = create_session(active_store, name=args.session_name)
                context = AgentContext()
                session_id = created.session_id
            else:
                context = AgentContext(messages=list(latest.messages))
                session_id = latest.session_id
        else:
            created = create_session(active_store, name=args.session_name)
            context = AgentContext()
            session_id = created.session_id
    except (OSError, SessionStoreError, ValueError) as caught:
        return _print_mode_failure(
            caught,
            events=events,
            error=error,
            session_started=False,
        )

    if events is not None:
        events.write(
            "session_start",
            session_id=session_id,
            persistent=explicit_durable_session and not args.no_session,
        )
        session_started = True

    active_registry = registry or ExtensionRegistry()
    if registry is None:
        register_sample_tools(active_registry)
        register_filesystem_tools(active_registry)
    resources = _load_resources(args)

    def on_event(event: SessionEvent) -> None:
        if events is None or not isinstance(event, MessageEvent):
            return
        message = event.message
        if message.role == "user":
            events.write("user", content=message.content)
        if message.thinking:
            events.write("thinking", content=message.thinking)
        if message.tool_call is not None:
            events.write(
                "tool_call",
                name=message.tool_call.name,
                arguments=dict(message.tool_call.arguments),
                call_id=message.tool_call.call_id,
            )
        elif message.role == "assistant":
            events.write("assistant", content=message.content)
        elif message.role == "tool":
            events.write(
                "tool_result",
                content=message.content,
                call_id=message.tool_call_id,
            )

    config = ProviderConfig(
        name=args.provider_name or args.provider,
        provider_type=args.provider if args.provider == "custom" else None,
        model=args.model,
        base_url=args.base_url,
        api_key=args.api_key,
        copilot_token=args.copilot_token,
        reasoning_effort_field=args.reasoning_effort_field,
        reasoning_effort=(
            None if args.reasoning_effort == "none" else args.reasoning_effort
        ),
        tool_prompt_role=args.tool_prompt_role,
    )
    try:
        if not args.provider:
            raise CommandError("provider is not configured")
        provider = (provider_factory or create_provider)(config)
        session = CodingSession(
            provider=provider,
            session_store=active_store,
            session_id=session_id,
            context=context,
            executor=active_registry,
            model=config.model,
            resources=resources,
            on_event=on_event,
        )
        result = session.prompt(
            task,
            preserve_task_whitespace=True,
        )
    except (AgentError, CommandError, ProviderError, SessionStoreError, ValueError) as caught:
        return _print_mode_failure(
            caught,
            events=events,
            error=error,
            session_started=session_started,
            session_id=session_id,
        )

    if result.status != "success":
        return _print_mode_failure(
            CommandError(result.error or "task failed"),
            events=events,
            error=error,
            session_started=session_started,
            session_id=session_id,
        )

    if events is not None:
        events.write("turn_end", success=True)
        events.write("session_end", session_id=session_id, success=True)
    else:
        print(result.content, file=output)
    return 0


def _print_mode_failure(
    caught: Exception,
    *,
    events: "_EventWriter | None",
    error: TextIO,
    session_started: bool,
    session_id: str = "",
) -> int:
    if events is not None:
        events.write("error", message=str(caught))
        if session_started:
            events.write(
                "session_end",
                session_id=session_id,
                success=False,
            )
    else:
        print(f"peon: {caught}", file=error)
    return 1


def _load_resources(args: argparse.Namespace) -> ResourceInventory:
    return ResourceLoader(
        include_skills=not args.no_skills,
        include_context_files=not args.no_context_files,
        trust_project=not args.no_project_context,
        skill_paths=tuple(args.skill_path),
        context_paths=tuple(args.context_file),
        system_prompt=args.system_prompt,
        system_prompt_path=args.system_prompt_file,
        append_system_prompt=tuple(args.append_system_prompt),
        append_system_prompt_paths=tuple(args.append_system_prompt_file),
    ).load()


class _EventWriter:
    def __init__(self, output: TextIO) -> None:
        self._output = output

    def write(self, event_type: str, **fields: object) -> None:
        payload = {"type": event_type, **fields}
        print(json.dumps(payload, separators=(",", ":"), default=str), file=self._output)


def create_provider(config: ProviderConfig) -> ModelProvider:
    """Create a provider adapter from generic command configuration."""
    assert config.supports_tools is not None
    provider_type = config.provider_type or config.name
    if provider_type == "openai-compatible":
        if config.base_url is None:
            raise CommandError("openai-compatible provider requires --base-url")
        return OpenAICompatibleProvider(
            base_url=config.base_url,
            api_key=config.api_key,
            model=config.model,
            reasoning_effort=config.reasoning_effort,
            temperature=config.temperature,
            max_completion_tokens=config.max_response_tokens,
            max_output_tokens=config.max_output_tokens,
            max_tokens=config.max_tokens,
            response_format=config.response_format,
            supports_tools=config.supports_tools,
            supports_chat_completions=config.supports_chat_completions,
            tool_prompt_role=config.tool_prompt_role,
        )
    if provider_type == "github-copilot":
        return GitHubCopilotProvider(
            token=config.copilot_token,
            model=config.model or "gpt-4o",
        )
    if provider_type == "custom":
        if config.base_url is None:
            raise CommandError("custom provider requires --base-url")
        return CustomProvider(
            base_url=config.base_url,
            api_key=config.api_key,
            model=config.model,
            request_fields=CustomRequestFields(
                reasoning_effort=config.reasoning_effort_field,
                temperature=config.temperature_field,
                max_response_tokens=config.max_response_tokens_field,
                max_output_tokens=config.max_output_tokens_field,
                max_tokens=config.max_tokens_field,
                response_format=config.response_format_field,
            ),
            response_fields=CustomResponseFields(
                content=config.response_content_field,
                thinking=config.response_thinking_field,
            ),
            reasoning_effort=config.reasoning_effort,
            temperature=config.temperature,
            max_response_tokens=config.max_response_tokens,
            max_output_tokens=config.max_output_tokens,
            max_tokens=config.max_tokens,
            response_format=config.response_format,
            supports_tools=config.supports_tools,
            supports_chat_completions=config.supports_chat_completions,
            tool_prompt_role=config.tool_prompt_role,
        )
    raise CommandError(f"provider adapter '{config.name}' is not available")