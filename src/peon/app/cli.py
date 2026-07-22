"""Command boundary for running a minimal Peon task."""

import argparse
import json
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TextIO
from uuid import uuid4

from peon.agent import (
    AgentContext,
    AgentError,
    ModelProvider,
    TraceContext,
    Usage,
)
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

from .coding_session import (
    MessageEvent,
    SessionEvent,
    TurnFinishedEvent,
)
from .session_controller import PromptIntent, SessionController
from .hosts import HostUnavailableError, resolve_host
from .observability import JsonlTraceSink, serialize_event
from .sessions import MemorySessionStore, SessionStore
from .resources import ResourceInventory, ResourceLoader


from .config import (
    CONFIG_SETTING_SPECS,
    PROFILE_SETTING_SPECS,
    PROVIDER_REASONING_CAPABILITIES,
    REASONING_EFFORTS,
    ProviderConfig,
    ProviderSettingSpec,
    SavedModel,
    cycle_reasoning_effort as _cycle_reasoning_effort_config,
    reasoning_effort_choices,
    saved_model_choices,
    select_saved_model as _select_saved_model_config,
)


def cycle_reasoning_effort(config: ProviderConfig, direction: int = 1) -> str:
    try:
        return _cycle_reasoning_effort_config(config, direction)
    except ValueError as error:
        raise CommandError(str(error)) from error


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


def select_saved_model(
    selection: str,
    choices: tuple[SavedModel, ...],
) -> SavedModel:
    try:
        return _select_saved_model_config(selection, choices)
    except ValueError as error:
        raise CommandError(str(error)) from error


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
        "--schema-version",
        type=int,
        choices=(1, 2),
        default=1,
        help="JSON event schema version; defaults to 1",
    )
    parser.add_argument(
        "--trace",
        type=Path,
        help="Append metadata-only performance traces as JSONL",
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
    run_id_factory: Callable[[], str] | None = None,
    turn_id_factory: Callable[[], str] | None = None,
    clock: Callable[[], float] | None = None,
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
        if args.schema_version != 1 and not args.event_mode:
            raise CommandError("--schema-version requires --events")
        task = " ".join(args.task).strip()
        if args.print_mode:
            if args.tui or args.mode is not None:
                raise CommandError("--print cannot be combined with interactive mode")
            try:
                resolve_host("jsonl" if args.event_mode else "print")
            except HostUnavailableError as caught:
                raise CommandError(str(caught)) from caught
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
                    schema_version=args.schema_version,
                    run_id_factory=run_id_factory,
                    turn_id_factory=turn_id_factory,
                    clock=clock,
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
                schema_version=args.schema_version,
                run_id_factory=run_id_factory,
                turn_id_factory=turn_id_factory,
                clock=clock,
            )
        if args.trace is not None:
            raise CommandError("--trace requires --print")
        if args.event_mode:
            raise CommandError("--events requires --print")
        mode: InteractionMode = args.mode or (
            "minimal" if args.tui or not task else "non-interactive"
        )
        host_identifier = (
            "textual"
            if mode == "minimal"
            else "print"
            if mode == "non-interactive"
            else mode
        )
        try:
            resolve_host(host_identifier)
        except HostUnavailableError as caught:
            if mode in {"fullscreen", "webapp"}:
                raise CommandError(f"{mode} mode is not available yet") from caught
            raise CommandError(str(caught)) from caught
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
            from .config import JsonProviderConfigStore
            try:
                from .textual_tui import run_textual_tui
            except ImportError as caught:
                raise CommandError(
                    "Interactive TUI requires the 'tui' optional extra. "
                    "Install with: pip install \"peon[tui]\" or uv add \"peon[tui]\""
                ) from caught

            return (tui_runner or run_textual_tui)(
                provider_factory=provider_factory,
                config_store=JsonProviderConfigStore(),
                registry=registry or ExtensionRegistry(),
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
                host_id=host_identifier,
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
        active_store = MemorySessionStore()
        session_record = active_store.create()
        controller = SessionController(
            provider=provider,
            session_store=active_store,
            session_id=session_record.session_id,
            model=config.model,
            resources=_load_resources(args),
        )
        result = controller.dispatch(PromptIntent(task))
        if result.status != "success":
            raise CommandError(result.error or "task failed")
        response = result.content or ""
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
    schema_version: int,
    run_id_factory: Callable[[], str] | None,
    turn_id_factory: Callable[[], str] | None,
    clock: Callable[[], float] | None,
) -> int:
    from .sessions import (
        JsonlSessionStore,
        MemorySessionStore,
        SessionStoreError,
        create_session,
        select_session,
    )

    events = _EventWriter(output, schema_version=schema_version) if event_mode else None
    run_id = (run_id_factory or (lambda: uuid4().hex))()
    trace_sink = JsonlTraceSink(args.trace) if args.trace is not None else None
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
            run_id=run_id,
        )

    if events is not None:
        events.write(
            "session_start",
            session_id=session_id,
            run_id=run_id,
            persistent=explicit_durable_session and not args.no_session,
        )
        session_started = True

    active_registry = registry or ExtensionRegistry(
        trace_sink=trace_sink,
        trace_context=TraceContext(
            session_id=session_id,
            run_id=run_id,
        ),
        trace_clock=clock or time.monotonic,
    )
    if registry is None:
        register_sample_tools(active_registry)
        register_filesystem_tools(active_registry)

    def on_event(event: SessionEvent) -> None:
        if events is None:
            return
        if events.schema_version == 2:
            events.write_event(event)
            return
        if isinstance(event, TurnFinishedEvent):
            if event.result.status == "success":
                events.write(
                    "turn_end",
                    **_event_correlation(event),
                    success=True,
                    status=event.result.status,
                    duration=event.duration,
                    usage=_serialize_usage(event.result.usage),
                )
            else:
                events.write(
                    "error",
                    **_event_correlation(event),
                    message=event.result.error or "task failed",
                    status=event.result.status,
                    duration=event.duration,
                    usage=_serialize_usage(event.result.usage),
                )
            return
        if not isinstance(event, MessageEvent):
            return
        message = event.message
        if message.role == "user":
            events.write(
                "user",
                **_event_correlation(event),
                content=message.content,
            )
        if message.thinking:
            events.write(
                "thinking",
                **_event_correlation(event),
                content=message.thinking,
            )
        if message.tool_call is not None:
            events.write(
                "tool_call",
                **_event_correlation(event),
                name=message.tool_call.name,
                arguments=dict(message.tool_call.arguments),
                call_id=message.tool_call.call_id,
            )
        elif message.role == "assistant":
            events.write(
                "assistant",
                **_event_correlation(event),
                content=message.content,
            )
        elif message.role == "tool":
            events.write(
                "tool_result",
                **_event_correlation(event),
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
        if trace_sink is None:
            resources = _load_resources(args)
        else:
            resources = _load_resources(
                args,
                trace_sink=trace_sink,
                trace_context=TraceContext(
                    session_id=session_id,
                    run_id=run_id,
                ),
                trace_clock=clock or time.monotonic,
            )
        if not args.provider:
            raise CommandError("provider is not configured")
        provider = (provider_factory or create_provider)(config)
        controller = SessionController(
            provider=provider,
            session_store=active_store,
            session_id=session_id,
            context=context,
            executor=active_registry,
            model=config.model,
            resources=resources,
            run_id=run_id,
            clock=clock or time.monotonic,
            id_factory=turn_id_factory or (lambda: uuid4().hex),
            on_event=on_event,
            trace_sink=trace_sink,
            trace_provider=args.provider_name or args.provider,
            event_utc_clock=events.utc_clock if events is not None else None,
            event_sequence_start=(events.next_sequence if events is not None else 0),
        )
        result = controller.dispatch(
            PromptIntent(task, preserve_whitespace=True),
        )
    except (
        AgentError,
        CommandError,
        OSError,
        ProviderError,
        SessionStoreError,
        ValueError,
    ) as caught:
        return _print_mode_failure(
            caught,
            events=events,
            error=error,
            session_started=session_started,
            session_id=session_id,
            run_id=run_id,
        )

    if result.status != "success":
        if events is not None:
            events.write(
                "session_end",
                session_id=session_id,
                run_id=run_id,
                success=False,
                status=result.status,
            )
        else:
            print(f"peon: {result.error or 'task failed'}", file=error)
        return 1

    if events is not None:
        events.write(
            "session_end",
            session_id=session_id,
            run_id=run_id,
            success=True,
            status=result.status,
        )
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
    run_id: str = "",
) -> int:
    if events is not None:
        events.write(
            "error",
            session_id=session_id,
            run_id=run_id,
            message=str(caught),
            status="error",
        )
        if session_started:
            events.write(
                "session_end",
                session_id=session_id,
                run_id=run_id,
                success=False,
                status="error",
            )
    else:
        print(f"peon: {caught}", file=error)
    return 1


def _event_correlation(event: SessionEvent) -> dict[str, object]:
    return {
        "session_id": event.session_id,
        "run_id": event.run_id,
        "turn_id": event.turn_id,
    }


def _serialize_usage(usage: Usage | None) -> dict[str, object] | None:
    if usage is None:
        return None
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_tokens": usage.cache_tokens,
        "cost": usage.cost,
        "currency": usage.currency,
    }


def _load_resources(
    args: argparse.Namespace,
    *,
    trace_sink=None,
    trace_context: TraceContext | None = None,
    trace_clock: Callable[[], float] | None = None,
) -> ResourceInventory:
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
        trace_sink=trace_sink,
        trace_context=trace_context,
        trace_clock=trace_clock,
    ).load()


class _EventWriter:
    def __init__(
        self,
        output: TextIO,
        *,
        schema_version: int = 1,
        utc_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._output = output
        self._schema_version = schema_version
        self._sequence = 0
        self._utc_clock = utc_clock or (lambda: datetime.now(timezone.utc))

    @property
    def schema_version(self) -> int:
        return self._schema_version

    @property
    def utc_clock(self) -> Callable[[], datetime]:
        return self._utc_clock

    @property
    def next_sequence(self) -> int:
        return self._sequence

    def write_event(self, event: SessionEvent) -> None:
        payload = serialize_event(event, schema_version=self._schema_version, strict=True)
        if self._schema_version == 2:
            event_sequence = payload.get("sequence")
            if isinstance(event_sequence, int):
                self._sequence = max(self._sequence, event_sequence + 1)
        print(json.dumps(payload, separators=(",", ":"), default=str), file=self._output)

    def write(self, event_type: str, **fields: object) -> None:
        if self._schema_version == 2:
            fields = {
                **fields,
                "timestamp": self._utc_clock().isoformat(),
                "sequence": self._sequence,
            }
            self._sequence += 1
        payload = serialize_event(
            {"type": event_type, **fields},
            schema_version=self._schema_version,
            strict=self._schema_version == 2,
        )
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