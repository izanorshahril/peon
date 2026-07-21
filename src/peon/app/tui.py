"""Interactive terminal session for Peon."""

from __future__ import annotations

import getpass
from pathlib import Path
import shutil
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from typing import TextIO

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion, CompleteEvent
from prompt_toolkit.document import Document

from peon.agent import (
    AgentContext,
    ModelProvider,
    ToolExecutionContext,
    Usage,
)
from peon.ai import ProviderError
from peon.extensions import (
    ExtensionRegistry,
    register_filesystem_tools,
    register_sample_tools,
)

from .cli import (
    CommandError,
    ProviderConfig,
    ProviderFactory,
    ProviderSettingSpec,
    REQUEST_FIELD_SETTING_SPECS,
    RESPONSE_FIELD_SETTING_SPECS,
    SavedModel,
    create_provider,
    cycle_reasoning_effort,
    provider_config_setting_specs,
    saved_model_choices,
    select_saved_model,
    update_provider_setting,
)
from .config import (
    GENERAL_SETTING_SPECS,
    UI_SETTING_SPECS,
    JsonProviderConfigStore,
    ProviderConfigStore,
    filter_enabled_tools,
    filter_tool_executor,
    load_ui_config,
    save_ui_config,
    update_saved_provider,
    update_general_setting,
    update_tool_setting,
    update_ui_setting,
)
from .commands import DEFAULT_COMMAND_CATALOG, CommandDefinition
from .coding_session import TurnResult
from .session_controller import (
    CommandErrorOutcome,
    CommandIntent,
    HelpOutcome,
    PromptIntent,
    ReasoningOutcome,
    SessionController,
    SessionInfoOutcome,
    SkillsOutcome,
    ToolsOutcome,
)
from .hosts import HostUnavailableError, resolve_host
from .resources import (
    ResourceInventory,
    apply_resource_prompt,
    conversation_messages_without_resource_prompt,
    load_skill_into_context,
)
from .sessions import (
    JsonlSessionStore,
    MemorySessionStore,
    SessionRecord,
    SessionStore,
    SessionStoreError,
    create_session,
    discard_empty_session,
    format_session_info,
    format_session_summary,
    merge_usage,
    select_session,
    session_interaction_count,
)

InputFunction = Callable[[str], str]
SecretInputFunction = Callable[[str], str]

_DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
_PEON_VERSION = "0.2.0"
_PROVIDER_OPTIONS = (
    ("openai-compatible", "OpenAI-compatible"),
    ("github-copilot", "GitHub Copilot"),
    ("custom", "Custom provider"),
)
class SlashCommandCompleter(Completer):
    """Suggest slash commands while the user types a command prefix."""

    def get_completions(
        self,
        document: Document,
        complete_event: CompleteEvent,
    ) -> Iterator[Completion]:
        del complete_event
        text = document.text
        if not text.startswith("/") or any(character.isspace() for character in text):
            return
        for match in DEFAULT_COMMAND_CATALOG.search(text):
            command = match.command
            candidates = ", ".join(command.candidate_names)
            metadata = command.description
            if candidates:
                metadata = f"{metadata} (also: {candidates})"
            if match.is_reserved:
                metadata = f"{metadata} [reserved]"
            yield Completion(
                command.name,
                start_position=-len(text),
                display=command.name,
                display_meta=metadata,
            )


def _create_input_function() -> InputFunction:
    session: PromptSession[str] = PromptSession(
        completer=SlashCommandCompleter(),
        complete_while_typing=True,
    )
    return session.prompt


@dataclass(slots=True)
class TuiSession:
    provider: ModelProvider
    config: ProviderConfig
    context: AgentContext = field(default_factory=AgentContext)
    registry: ExtensionRegistry = field(default_factory=ExtensionRegistry)
    resources: ResourceInventory | None = None
    session_id: str = ""
    session_store: SessionStore = field(default_factory=MemorySessionStore)
    persisted_message_count: int = 0
    run_id: str = ""
    usage: Usage | None = None


def _terminal_rule() -> str:
    width = shutil.get_terminal_size((80, 24)).columns
    return "─" * max(40, min(width, 120))


def _print_header(*, output: TextIO) -> None:
    print(f" peon v{_PEON_VERSION}", file=output)
    print(
        " escape interrupt · ctrl+c/ctrl+d clear/exit · / commands · ! bash",
        file=output,
    )
    print(" Type /help for commands and /model for saved models.", file=output)


def _print_resource_summary(
    resources: ResourceInventory | None,
    *,
    output: TextIO,
) -> None:
    if resources is None:
        return
    print(file=output)
    for line in resources.startup_summary():
        print(line, file=output)


def _print_footer(session: TuiSession, *, output: TextIO) -> None:
    print(_terminal_rule(), file=output)
    print(f"{Path.cwd()} (peon)", file=output)
    print(
        f"({session.config.name}) {session.config.model or 'no model'} "
        "• minimal",
        file=output,
    )


def _select_provider(
    *,
    input_fn: InputFunction,
    output: TextIO,
    error: TextIO,
) -> str | None:
    print("Providers:", file=output)
    for index, (_name, label) in enumerate(_PROVIDER_OPTIONS, start=1):
        print(f"  {index}. {label}", file=output)
    selection = input_fn(
        f"Select provider [1-{len(_PROVIDER_OPTIONS)}] (default: 1): "
    ).strip()
    selection = selection or "1"
    if not selection.isdigit():
        print("peon: select a provider by number", file=error)
        return None
    index = int(selection) - 1
    if not 0 <= index < len(_PROVIDER_OPTIONS):
        print("peon: select a provider by number", file=error)
        return None
    return _PROVIDER_OPTIONS[index][0]


def run_tui(
    *,
    provider_factory: ProviderFactory | None = None,
    input_fn: InputFunction | None = None,
    secret_input: SecretInputFunction | None = None,
    output: TextIO | None = None,
    error: TextIO | None = None,
    registry: ExtensionRegistry | None = None,
    config_store: ProviderConfigStore | None = None,
    session_store: SessionStore | None = None,
    user_top_blank_lines: int = 1,
    user_bottom_blank_lines: int = 1,
    message_left_padding: int = 1,
    continue_session: bool = False,
    no_session: bool = False,
    session_target: str | None = None,
    session_name: str | None = None,
    resources: ResourceInventory | None = None,
    host_id: str | None = None,
) -> int:
    """Run an interactive Peon conversation until the user exits."""
    output = output or sys.stdout
    error = error or sys.stderr
    secret_input = secret_input or getpass.getpass
    selected_host_id = host_id or (
        "prompt-toolkit" if input_fn is not None else "textual"
    )
    try:
        selected_host = resolve_host(selected_host_id)
    except HostUnavailableError as caught:
        print(f"peon: {caught}", file=error)
        return 1
    if selected_host.role != "interactive":
        print(
            f"peon: host '{selected_host.identifier}' is not an interactive host",
            file=error,
        )
        return 1
    active_registry = registry or ExtensionRegistry()
    active_config_store = config_store or JsonProviderConfigStore()
    active_session_store = session_store or _default_session_store(active_config_store)
    if no_session:
        active_session_store = MemorySessionStore()
    if registry is None:
        register_sample_tools(active_registry)
        register_filesystem_tools(active_registry)

    if selected_host.identifier == "textual":
        from .textual_tui import run_textual_tui

        return run_textual_tui(
            provider_factory=provider_factory,
            output=output,
            error=error,
            registry=active_registry,
            config_store=active_config_store,
            session_store=active_session_store,
            user_top_blank_lines=user_top_blank_lines,
            user_bottom_blank_lines=user_bottom_blank_lines,
            message_left_padding=message_left_padding,
            continue_session=continue_session,
            no_session=no_session,
            session_target=session_target,
            session_name=session_name,
            resources=resources,
        )

    if input_fn is None:
        input_fn = _create_input_function()

    _print_header(output=output)
    try:
        active_session_store, session_id, context = _load_starting_session(
            active_session_store,
            error=error,
            continue_session=continue_session,
            session_target=session_target,
            session_name=session_name,
        )
    except SessionStoreError:
        return 1
    if resources is not None:
        apply_resource_prompt(context, resources)
    _print_resource_summary(resources, output=output)
    session = _restore_session(
        provider_factory=provider_factory,
        config_store=active_config_store,
        output=output,
        error=error,
        context=context,
        registry=active_registry,
        resources=resources,
        session_id=session_id,
        session_store=active_session_store,
    )
    try:
        while session is None:
            session = _configure_session(
                provider_factory=provider_factory,
                input_fn=input_fn,
                secret_input=secret_input,
                output=output,
                error=error,
                context=context,
                registry=active_registry,
                resources=resources,
                config_store=active_config_store,
                session_id=session_id,
                session_store=active_session_store,
            )
        result, session = _conversation_loop(
            session,
            provider_factory=provider_factory,
            input_fn=input_fn,
            secret_input=secret_input,
            output=output,
            error=error,
            config_store=active_config_store,
        )
        discarded = _discard_empty_active_session(session)
        _print_footer(session, output=output)
        if not discarded:
            _print_resume_command(session, output=output)
        return result
    except (EOFError, KeyboardInterrupt):
        if session is not None:
            discarded = _discard_empty_active_session(session)
        else:
            discarded = discard_empty_session(active_session_store, session_id)
        _print_resume_command(
            None if discarded else session,
            output=output,
            session_id=None if discarded else session_id,
            session_store=active_session_store,
        )
        print("\nGoodbye.", file=output)
        return 0


def _default_session_store(config_store: ProviderConfigStore) -> SessionStore:
    if isinstance(config_store, JsonProviderConfigStore):
        return JsonlSessionStore()
    return MemorySessionStore()


def _load_starting_session(
    store: SessionStore,
    *,
    error: TextIO,
    continue_session: bool = False,
    session_target: str | None = None,
    session_name: str | None = None,
) -> tuple[SessionStore, str, AgentContext]:
    if session_target is not None:
        try:
            selected = select_session(store, session_target)
        except SessionStoreError as caught:
            print(f"peon: could not open saved session: {caught}", file=error)
            raise
        return (
            store,
            selected.session_id,
            AgentContext(messages=list(selected.messages)),
        )
    if continue_session:
        try:
            latest = store.load_latest()
        except SessionStoreError as caught:
            print(f"peon: could not resume saved session: {caught}", file=error)
            latest = None
        if latest is not None:
            return store, latest.session_id, AgentContext(messages=list(latest.messages))
    try:
        created = create_session(store, name=session_name)
    except (OSError, SessionStoreError) as caught:
        print(f"peon: could not create saved session: {caught}", file=error)
        fallback = MemorySessionStore()
        created = fallback.create(name=session_name)
        return fallback, created.session_id, AgentContext()
    return store, created.session_id, AgentContext()


def _session_label(session: SessionRecord) -> str:
    name = f" · {session.name}" if session.name else ""
    return f"{format_session_summary(session)}{name}"


def _print_session_info(
    session: TuiSession,
    *,
    output: TextIO,
    error: TextIO,
) -> None:
    try:
        record = session.session_store.load(session.session_id)
    except (OSError, SessionStoreError) as caught:
        print(f"peon: could not inspect session: {caught}", file=error)
        return
    messages = tuple(
        conversation_messages_without_resource_prompt(
            session.context.messages,
            session.resources,
        )
    )
    record = replace(record, messages=messages)
    for line in format_session_info(
        record,
        store=session.session_store,
        usage=session.usage,
    ):
        print(line, file=output)


def _select_session_for_tui(
    store: SessionStore,
    *,
    argument: str,
    input_fn: InputFunction,
    output: TextIO,
    error: TextIO,
    delimiter: bool = True,
    current_session_id: str | None = None,
) -> SessionRecord | None:
    if argument:
        try:
            return select_session(store, argument)
        except SessionStoreError as caught:
            print(f"peon: could not open saved session: {caught}", file=error)
            return None
    try:
        sessions = tuple(
            saved
            for saved in store.list_sessions()
            if session_interaction_count(saved) > 0
            and saved.session_id != current_session_id
        )
    except (OSError, SessionStoreError) as caught:
        print(f"peon: could not list saved sessions: {caught}", file=error)
        return None
    if not sessions:
        print("No saved sessions.", file=output)
        return None
    print("Saved sessions:", file=output)
    for index, saved in enumerate(sessions, 1):
        print(
            f"  {index}. {format_session_summary(saved, delimiter=delimiter)}"
            + (f" · {saved.name}" if saved.name else ""),
            file=output,
        )
    selection = input_fn("Session (blank to cancel): ").strip()
    if not selection:
        print("Session selection cancelled.", file=output)
        return None
    if selection.isdigit() and 1 <= int(selection) <= len(sessions):
        return sessions[int(selection) - 1]
    try:
        return select_session(store, selection)
    except SessionStoreError as caught:
        print(f"peon: could not open saved session: {caught}", file=error)
        return None


def _open_session(session: TuiSession, selected: SessionRecord) -> TuiSession:
    if (
        selected.session_id != session.session_id
        and not any(message.role == "user" for message in session.context.messages)
    ):
        discard_empty_session(session.session_store, session.session_id)
    context = AgentContext(messages=list(selected.messages))
    if session.resources is not None:
        apply_resource_prompt(context, session.resources)
    return replace(
        session,
        context=context,
        session_id=selected.session_id,
        persisted_message_count=len(context.messages),
        usage=None,
    )


def _fork_session(
    session: TuiSession,
    *,
    name: str | None,
) -> TuiSession:
    created = create_session(
        session.session_store,
        parent_id=session.session_id,
        name=name or None,
    )
    messages = tuple(
        conversation_messages_without_resource_prompt(
            session.context.messages,
            session.resources,
        )
    )
    for message in messages:
        session.session_store.append(created.session_id, message)
    context = AgentContext(messages=list(messages))
    if session.resources is not None:
        apply_resource_prompt(context, session.resources)
    return replace(
        session,
        context=context,
        session_id=created.session_id,
        persisted_message_count=len(context.messages),
        usage=None,
    )


def _print_resume_command(
    session: TuiSession | None,
    *,
    output: TextIO,
    session_id: str | None = None,
    session_store: SessionStore | None = None,
) -> None:
    if session is not None:
        session_id = session.session_id
        session_store = session.session_store
    if session_id is not None and isinstance(session_store, JsonlSessionStore):
        print(
            f"Resume with: peon --session {session_id}",
            file=output,
        )


def _discard_empty_active_session(session: TuiSession) -> bool:
    if any(message.role == "user" for message in session.context.messages):
        return False
    return discard_empty_session(session.session_store, session.session_id)


def _configure_session(
    *,
    provider_factory: ProviderFactory | None,
    input_fn: InputFunction,
    secret_input: SecretInputFunction,
    output: TextIO,
    error: TextIO,
    context: AgentContext,
    registry: ExtensionRegistry,
    resources: ResourceInventory | None,
    config_store: ProviderConfigStore,
    session_id: str,
    session_store: SessionStore,
    persisted_message_count: int | None = None,
) -> TuiSession | None:
    provider_name = _select_provider(input_fn=input_fn, output=output, error=error)
    if provider_name is None:
        return None

    if provider_name == "openai-compatible":
        base_url = input_fn(
            f"Base URL (default: {_DEFAULT_OPENAI_BASE_URL}): "
        ).strip()
        base_url = base_url or _DEFAULT_OPENAI_BASE_URL
        api_key = secret_input("API key: ").strip()
        config = ProviderConfig(
            name=provider_name,
            base_url=base_url,
            api_key=api_key,
        )
    elif provider_name == "custom":
        custom_name = input_fn("Custom provider name (default: custom provider): ").strip()
        base_url = input_fn("Proxy URL: ").strip()
        api_key = secret_input("API key (optional): ").strip()
        config = ProviderConfig(
            name=custom_name or "custom provider",
            provider_type="custom",
            base_url=base_url,
            api_key=api_key or None,
        )
    else:
        token = secret_input(
            "Copilot token (leave blank to use GITHUB_COPILOT_TOKEN): "
        ).strip()
        config = ProviderConfig(
            name=provider_name,
            copilot_token=token or None,
        )

    try:
        provider = (provider_factory or create_provider)(config)
        if provider_name in {"openai-compatible", "custom"}:
            models = _discover_models(provider, error=error)
            if not models:
                raise CommandError("provider did not advertise any models")
            selected_model = _select_default_model(
                models,
                input_fn=input_fn,
                output=output,
            )
            config = ProviderConfig(
                name=config.name,
                provider_type=config.provider_type,
                model=selected_model,
                models=models,
                base_url=config.base_url,
                api_key=config.api_key,
                copilot_token=config.copilot_token,
                reasoning_effort_field=config.reasoning_effort_field,
                reasoning_effort=config.reasoning_effort,
            )
            provider = (provider_factory or create_provider)(config)
        else:
            config = ProviderConfig(
                name=config.name,
                provider_type=config.provider_type,
                model="gpt-4o",
                base_url=config.base_url,
                api_key=config.api_key,
                copilot_token=config.copilot_token,
                reasoning_effort_field=config.reasoning_effort_field,
                reasoning_effort=config.reasoning_effort,
            )
            provider = (provider_factory or create_provider)(config)
    except (CommandError, ProviderError, ValueError) as caught:
        print(f"peon: {caught}", file=error)
        return None

    _save_configuration(config_store, config, error=error)
    print(f"Provider configured: {config.name} ({config.model})", file=output)
    return TuiSession(
        provider=provider,
        config=config,
        context=context,
        registry=registry,
        resources=resources,
        session_id=session_id,
        session_store=session_store,
        persisted_message_count=(
            len(context.messages)
            if persisted_message_count is None
            else persisted_message_count
        ),
    )


def _restore_session(
    *,
    provider_factory: ProviderFactory | None,
    config_store: ProviderConfigStore,
    output: TextIO,
    error: TextIO,
    context: AgentContext,
    registry: ExtensionRegistry,
    resources: ResourceInventory | None,
    session_id: str,
    session_store: SessionStore,
) -> TuiSession | None:
    configs = config_store.load_all()
    if not configs:
        return None
    config = config_store.load()
    if config is None:
        return None
    try:
        provider = (provider_factory or create_provider)(config)
    except (CommandError, ProviderError, ValueError) as caught:
        print(f"peon: saved provider configuration is unavailable: {caught}", file=error)
        return None

    print(
        f"Using saved provider: {config.name} ({config.model}); "
        "use /provider to change it.",
        file=output,
    )
    return TuiSession(
        provider=provider,
        config=config,
        context=context,
        registry=registry,
        resources=resources,
        session_id=session_id,
        session_store=session_store,
        persisted_message_count=len(context.messages),
    )


def _select_saved_provider(
    configs: tuple[ProviderConfig, ...],
    *,
    input_fn: InputFunction,
    output: TextIO,
    error: TextIO,
) -> ProviderConfig | None:
    if len(configs) == 1:
        return configs[0]
    print("Saved providers:", file=output)
    for index, config in enumerate(configs, start=1):
        print(
            f"  {index}. {config.name} ({config.model or 'no model'})",
            file=output,
        )
    selection = input_fn(f"Select provider [1-{len(configs)}]: ").strip()
    if not selection.isdigit():
        print("peon: select a provider by number", file=error)
        return None
    index = int(selection) - 1
    if not 0 <= index < len(configs):
        print("peon: select a provider by number", file=error)
        return None
    return configs[index]


def _save_configuration(
    config_store: ProviderConfigStore,
    config: ProviderConfig,
    *,
    error: TextIO,
) -> None:
    try:
        config_store.save(config)
    except OSError as caught:
        print(f"peon: could not save provider configuration: {caught}", file=error)


def _discover_models(
    provider: ModelProvider,
    *,
    error: TextIO,
) -> tuple[str, ...]:
    list_models = getattr(provider, "list_models", None)
    if not callable(list_models):
        return ()
    try:
        models = tuple(list_models())
    except ProviderError as caught:
        print(f"peon: model discovery failed: {caught}", file=error)
        return ()
    if not all(isinstance(model, str) and model.strip() for model in models):
        print("peon: provider returned invalid model IDs", file=error)
        return ()
    return models


def _select_model(selection: str, models: tuple[str, ...]) -> str:
    if selection.isdigit():
        index = int(selection) - 1
        if 0 <= index < len(models):
            return models[index]
    if selection in models:
        return selection
    raise CommandError("select a model by number or exact model ID")


def _select_default_model(
    models: tuple[str, ...],
    *,
    input_fn: InputFunction,
    output: TextIO,
) -> str:
    if len(models) == 1:
        print(f"Using detected model: {models[0]}", file=output)
        return models[0]
    _print_models(models, output=output)
    return _select_model(
        input_fn(f"Select default model [1-{len(models)}]: ").strip(),
        models,
    )


def _print_models(models: tuple[str, ...], *, output: TextIO) -> None:
    if not models:
        print("No saved models. Use /provider to discover models.", file=output)
        return
    print("Available models:", file=output)
    for index, model in enumerate(models, start=1):
        print(f"  {index}. {model}", file=output)


def _print_saved_models(
    choices: tuple[SavedModel, ...],
    *,
    output: TextIO,
) -> None:
    if not choices:
        print("No saved models. Use /provider to discover models.", file=output)
        return
    print("Available models:", file=output)
    for index, choice in enumerate(choices, start=1):
        print(f"  {index}. {choice.label}", file=output)


def _select_setting(
    selection: str,
    specs: tuple[ProviderSettingSpec, ...],
) -> ProviderSettingSpec | None:
    if selection.isdigit() and 1 <= int(selection) <= len(specs):
        return specs[int(selection) - 1]
    return next((spec for spec in specs if spec.key == selection), None)


def _format_setting_value(value: object) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _print_provider_settings(
    config: ProviderConfig,
    specs: tuple[ProviderSettingSpec, ...],
    *,
    output: TextIO,
) -> None:
    for index, spec in enumerate(specs, 1):
        value = getattr(config, spec.field_name)
        if spec.value_kind == "secret" and value:
            value = "configured"
        print(f"  {index}. {spec.label}: {_format_setting_value(value)}", file=output)


def _configure_ui_settings(
    *,
    input_fn: InputFunction,
    output: TextIO,
    error: TextIO,
    config_store: ProviderConfigStore,
) -> None:
    ui_config = load_ui_config(config_store)
    while True:
        print("UI settings:", file=output)
        for index, (key, label, field_name) in enumerate(UI_SETTING_SPECS, 1):
            print(f"  {index}. {label}: {getattr(ui_config, field_name)}", file=output)
        selection = input_fn("UI setting (blank to go back): ").strip()
        if not selection:
            return
        if selection.isdigit() and 1 <= int(selection) <= len(UI_SETTING_SPECS):
            key, label, _field_name = UI_SETTING_SPECS[int(selection) - 1]
        else:
            match = next((spec for spec in UI_SETTING_SPECS if spec[0] == selection), None)
            if match is None:
                print("peon: select a UI setting by number or exact name", file=error)
                continue
            key, label, _field_name = match
        value = input_fn(f"{label}: ").strip()
        try:
            ui_config = update_ui_setting(ui_config, key, value)
            save_ui_config(config_store, ui_config)
        except (OSError, ValueError) as caught:
            print(f"peon: UI setting update failed: {caught}", file=error)
            continue
        print(f"Updated {label}. The fullscreen UI applies it immediately.", file=output)


def _configure_tool_settings(
    *,
    registry: ExtensionRegistry,
    input_fn: InputFunction,
    output: TextIO,
    error: TextIO,
    config_store: ProviderConfigStore,
) -> None:
    ui_config = load_ui_config(config_store)
    tool_names = tuple(
        dict.fromkeys(
            (
                *ui_config.enabled_tools,
                *(tool.name for tool in registry.tools),
            )
        )
    )
    while True:
        print("Tool availability:", file=output)
        for index, name in enumerate(tool_names, 1):
            state = "true" if name in ui_config.enabled_tools else "false"
            print(f"  {index}. {name}: {state}", file=output)
        selection = input_fn("Tool (blank to go back): ").strip()
        if not selection:
            return
        if selection.isdigit() and 1 <= int(selection) <= len(tool_names):
            tool_name = tool_names[int(selection) - 1]
        else:
            selected_tool_name = next(
                (name for name in tool_names if name == selection),
                None,
            )
            if selected_tool_name is None:
                print("peon: select a tool by number or exact name", file=error)
                continue
            tool_name = selected_tool_name
        current = tool_name in ui_config.enabled_tools
        value = input_fn(
            f"Enable {tool_name} [{str(not current).lower()} to toggle]: "
        ).strip() or str(not current).lower()
        try:
            ui_config = update_tool_setting(ui_config, tool_name, value)
            save_ui_config(config_store, ui_config)
        except (OSError, ValueError) as caught:
            print(f"peon: tool setting update failed: {caught}", file=error)
            continue
        print(f"Updated {tool_name}: {tool_name in ui_config.enabled_tools}.", file=output)


def _configure_general_settings(
    *,
    input_fn: InputFunction,
    output: TextIO,
    error: TextIO,
    config_store: ProviderConfigStore,
) -> None:
    ui_config = load_ui_config(config_store)
    settings = tuple(
        spec for spec in GENERAL_SETTING_SPECS if spec[2] is not None
    )
    while True:
        print("General settings:", file=output)
        for index, (_key, label, field_name) in enumerate(settings, 1):
            assert field_name is not None
            print(
                f"  {index}. {label}: {str(getattr(ui_config, field_name)).lower()}",
                file=output,
            )
        selection = input_fn("General setting (blank to go back): ").strip()
        if not selection:
            return
        if selection.isdigit() and 1 <= int(selection) <= len(settings):
            key, label, _field_name = settings[int(selection) - 1]
        else:
            match = next((spec for spec in settings if spec[0] == selection), None)
            if match is None:
                print("peon: select a general setting by number or exact name", file=error)
                continue
            key, label, _field_name = match
        value = input_fn(f"{label} [true/false]: ").strip()
        try:
            ui_config = update_general_setting(ui_config, key, value)
            save_ui_config(config_store, ui_config)
        except (OSError, ValueError) as caught:
            print(f"peon: general setting update failed: {caught}", file=error)
            continue
        print(f"Updated {label}: {getattr(ui_config, _field_name)}.", file=output)


def _provider_types(configs: tuple[ProviderConfig, ...]) -> tuple[tuple[str, str], ...]:
    available = {config.provider_type or config.name for config in configs}
    return tuple(
        (provider_type, label)
        for provider_type, label in _PROVIDER_OPTIONS
        if provider_type in available
    )


def _configure_provider_category(
    session: TuiSession,
    config: ProviderConfig,
    specs: tuple[ProviderSettingSpec, ...],
    *,
    provider_factory: ProviderFactory | None,
    input_fn: InputFunction,
    secret_input: SecretInputFunction,
    output: TextIO,
    error: TextIO,
    config_store: ProviderConfigStore,
) -> TuiSession:
    while True:
        _print_provider_settings(config, specs, output=output)
        selection = input_fn("Setting (blank to go back): ").strip()
        if not selection:
            return session
        spec = _select_setting(selection, specs)
        if spec is None:
            print("peon: select a setting by number or exact name", file=error)
            continue
        current = getattr(config, spec.field_name)
        if spec.value_kind == "toggle":
            value = str(not bool(current)).lower()
        else:
            choices = f" ({'|'.join(spec.choices)})" if spec.choices else ""
            prompt = f"{spec.label}{choices}: "
            value = (
                secret_input(prompt).strip()
                if spec.value_kind == "secret"
                else input_fn(prompt).strip()
            )
        try:
            updated = update_provider_setting(config, spec.key, value)
            provider = (provider_factory or create_provider)(updated)
            update_saved_provider(config_store, config, updated)
        except (CommandError, ProviderError, OSError, ValueError) as caught:
            print(f"peon: setting update failed: {caught}", file=error)
            continue
        config = updated
        session = TuiSession(
            provider=provider,
            config=config,
            context=session.context,
            registry=session.registry,
            resources=session.resources,
            session_id=session.session_id,
            session_store=session.session_store,
            persisted_message_count=session.persisted_message_count,
        )
        print(f"Updated {spec.label}.", file=output)


def _configure_provider_profile(
    session: TuiSession,
    config: ProviderConfig,
    *,
    provider_factory: ProviderFactory | None,
    input_fn: InputFunction,
    secret_input: SecretInputFunction,
    output: TextIO,
    error: TextIO,
    config_store: ProviderConfigStore,
) -> TuiSession:
    while True:
        provider_type = config.provider_type or config.name
        sections: list[tuple[str, str, tuple[ProviderSettingSpec, ...]]] = [
            ("name", "Name", (ProviderSettingSpec("name", "Name", "name", "text"),)),
            ("config", "Config", provider_config_setting_specs(config)),
        ]
        if provider_type == "custom":
            sections.extend(
                [
                    ("request", "Request fields", REQUEST_FIELD_SETTING_SPECS),
                    ("response", "Response fields", RESPONSE_FIELD_SETTING_SPECS),
                ]
            )
        print(f"Provider settings: {config.name}", file=output)
        for index, (_key, label, _specs) in enumerate(sections, 1):
            print(f"  {index}. {label}", file=output)
        selection = input_fn("Section (blank to go back): ").strip()
        if not selection:
            return session
        section = (
            sections[int(selection) - 1]
            if selection.isdigit() and 1 <= int(selection) <= len(sections)
            else next((item for item in sections if item[0] == selection), None)
        )
        if section is None:
            print("peon: select a section by number or exact name", file=error)
            continue
        session = _configure_provider_category(
            session,
            config,
            section[2],
            provider_factory=provider_factory,
            input_fn=input_fn,
            secret_input=secret_input,
            output=output,
            error=error,
            config_store=config_store,
        )
        config = session.config


def _configure_settings(
    session: TuiSession,
    *,
    provider_factory: ProviderFactory | None,
    input_fn: InputFunction,
    secret_input: SecretInputFunction,
    output: TextIO,
    error: TextIO,
    config_store: ProviderConfigStore,
) -> TuiSession:
    while True:
        print("Settings:", file=output)
        print("  1. UI", file=output)
        print("  2. Saved provider", file=output)
        print("  3. Add provider", file=output)
        print("  4. General", file=output)
        print("  5. Tool availability", file=output)
        selection = input_fn("Section (blank to finish): ").strip()
        if not selection:
            return session
        if selection in {"1", "ui"}:
            _configure_ui_settings(
                input_fn=input_fn,
                output=output,
                error=error,
                config_store=config_store,
            )
            continue
        if selection in {"3", "add-provider"}:
            replacement = _configure_session(
                provider_factory=provider_factory,
                input_fn=input_fn,
                secret_input=secret_input,
                output=output,
                error=error,
                context=session.context,
                registry=session.registry,
                resources=session.resources,
                config_store=config_store,
                session_id=session.session_id,
                session_store=session.session_store,
                persisted_message_count=session.persisted_message_count,
            )
            session = replacement or session
            continue
        if selection in {"4", "general"}:
            _configure_general_settings(
                input_fn=input_fn,
                output=output,
                error=error,
                config_store=config_store,
            )
            continue
        if selection in {"5", "tools", "tool-availability"}:
            _configure_tool_settings(
                registry=session.registry,
                input_fn=input_fn,
                output=output,
                error=error,
                config_store=config_store,
            )
            continue
        if selection not in {"2", "saved-provider"}:
            print("peon: select a settings section", file=error)
            continue
        configs = config_store.load_all()
        provider_types = _provider_types(configs)
        if not provider_types:
            print("No saved providers.", file=output)
            continue
        print("Provider types:", file=output)
        for index, (_provider_type, label) in enumerate(provider_types, 1):
            print(f"  {index}. {label}", file=output)
        type_selection = input_fn("Provider type (blank to go back): ").strip()
        if not type_selection:
            continue
        selected_type = (
            provider_types[int(type_selection) - 1][0]
            if type_selection.isdigit() and 1 <= int(type_selection) <= len(provider_types)
            else type_selection
        )
        profiles = tuple(
            config
            for config in configs
            if (config.provider_type or config.name) == selected_type
        )
        if not profiles:
            print("peon: select a saved provider type", file=error)
            continue
        print("Saved providers:", file=output)
        for index, config in enumerate(profiles, 1):
            print(f"  {index}. {config.name}", file=output)
        profile_selection = input_fn("Provider (blank to go back): ").strip()
        if not profile_selection:
            continue
        selected_profile = (
            profiles[int(profile_selection) - 1]
            if profile_selection.isdigit() and 1 <= int(profile_selection) <= len(profiles)
            else next((config for config in profiles if config.name == profile_selection), None)
        )
        if selected_profile is None:
            print("peon: select a saved provider", file=error)
            continue
        session = _configure_provider_profile(
            session,
            selected_profile,
            provider_factory=provider_factory,
            input_fn=input_fn,
            secret_input=secret_input,
            output=output,
            error=error,
            config_store=config_store,
        )


def _update_active_provider_setting(
    session: TuiSession,
    command: CommandDefinition,
    argument: str,
    *,
    provider_factory: ProviderFactory | None,
    input_fn: InputFunction,
    secret_input: SecretInputFunction,
    output: TextIO,
    error: TextIO,
    config_store: ProviderConfigStore,
) -> TuiSession:
    setting = command.setting_key
    if setting is None:
        return session
    spec = next(
        spec
        for spec in provider_config_setting_specs(session.config)
        if spec.key == setting
    ) if setting != "name" else ProviderSettingSpec("name", "Name", "name", "text")
    current = getattr(session.config, spec.field_name)
    value = argument.strip()
    if not value and spec.value_kind == "toggle":
        value = str(not bool(current)).lower()
    elif not value and setting == "reasoning":
        try:
            value = cycle_reasoning_effort(session.config)
        except CommandError as caught:
            print(f"peon: setting update failed: {caught}", file=error)
            return session
    elif not value:
        choices = f" ({'|'.join(spec.choices)})" if spec.choices else ""
        prompt = f"{spec.label}{choices}: "
        value = (
            secret_input(prompt).strip()
            if spec.value_kind == "secret"
            else input_fn(prompt).strip()
        )
    try:
        config = update_provider_setting(session.config, setting, value)
        provider = (provider_factory or create_provider)(config)
        update_saved_provider(config_store, session.config, config)
    except (CommandError, ProviderError, OSError, ValueError) as caught:
        print(f"peon: setting update failed: {caught}", file=error)
        return session
    print(f"Updated {spec.label}: {_format_setting_value(getattr(config, spec.field_name))}", file=output)
    return TuiSession(
        provider=provider,
        config=config,
        context=session.context,
        registry=session.registry,
        resources=session.resources,
        session_id=session.session_id,
        session_store=session.session_store,
        persisted_message_count=session.persisted_message_count,
    )


def _switch_model(
    session: TuiSession,
    *,
    selection: SavedModel,
    provider_factory: ProviderFactory | None,
    output: TextIO,
    error: TextIO,
    config_store: ProviderConfigStore,
) -> TuiSession:
    if not selection.config.models:
        print("No saved models. Use /provider to discover models.", file=output)
        return session
    try:
        config = replace(selection.config, model=selection.model)
        provider = (provider_factory or create_provider)(config)
    except (CommandError, ProviderError, ValueError) as caught:
        print(f"peon: {caught}", file=error)
        return session
    _save_configuration(config_store, config, error=error)
    print(f"Model selected: {selection.label}", file=output)
    return TuiSession(
        provider=provider,
        config=config,
        context=session.context,
        registry=session.registry,
        session_id=session.session_id,
        session_store=session.session_store,
        persisted_message_count=session.persisted_message_count,
    )


def _conversation_loop(
    session: TuiSession,
    *,
    provider_factory: ProviderFactory | None,
    input_fn: InputFunction,
    secret_input: SecretInputFunction,
    output: TextIO,
    error: TextIO,
    config_store: ProviderConfigStore,
) -> tuple[int, TuiSession]:
    while True:
        print(_terminal_rule(), file=output)
        try:
            task = input_fn(" > ").strip()
        except KeyboardInterrupt:
            continue
        print(_terminal_rule(), file=output)
        if not task:
            continue
        if task.startswith("/"):
            session, should_exit = _handle_command(
                task,
                session,
                provider_factory=provider_factory,
                input_fn=input_fn,
                secret_input=secret_input,
                output=output,
                error=error,
                config_store=config_store,
            )
            if should_exit:
                return 0, session
            continue

        if task.startswith("!"):
            hidden = task.startswith("!!")
            command = task[2:] if hidden else task[1:]
            if not command.strip():
                print("bash command is required", file=error)
                continue
            if not any(tool.name == "bash" for tool in session.registry.tools):
                print("bash tool is not registered", file=error)
                continue
            try:
                result = session.registry.invoke_with_context(
                    "bash",
                    {"command": command.strip()},
                    ToolExecutionContext(),
                )
            except Exception as caught:
                print(str(caught), file=error)
                continue
            print(result, file=output)
            if hidden:
                continue
            task = f"Shell command `{command.strip()}` output:\n{result}"

        controller = SessionController(
            provider=session.provider,
            session_store=session.session_store,
            session_id=session.session_id,
            run_id=session.run_id or None,
            context=session.context,
            executor=filter_tool_executor(
                load_ui_config(config_store),
                session.registry,
            ),
            model=session.config.model,
            resources=session.resources,
        )
        session.run_id = controller.run_id
        response = controller.dispatch(PromptIntent(task))
        session.usage = merge_usage(session.usage, response.usage)
        if response.status != "success":
            print(
                f"peon: {response.error or 'task failed'}",
                file=error,
            )
            continue
        print(f"peon> {response.content or ''}", file=output)


def _dispatch_tui_controller_command(
    command: str,
    session: TuiSession,
    *,
    output: TextIO,
    error: TextIO,
    config_store: ProviderConfigStore,
) -> bool:
    name = command.split(maxsplit=1)[0].lower()
    invocation = DEFAULT_COMMAND_CATALOG.resolve(command)
    cmd_id = invocation.command.id if invocation is not None else None

    is_info_cmd = (
        name.startswith("/skill:")
        or cmd_id in ("help", "tools", "skills", "session", "reasoning")
        or (invocation is not None and invocation.command.id.startswith("skill:"))
    )
    if not is_info_cmd:
        return False

    ui_config = load_ui_config(config_store)
    controller = SessionController(
        provider=session.provider,
        session_store=session.session_store,
        session_id=session.session_id,
        run_id=session.run_id or None,
        context=session.context,
        executor=filter_tool_executor(ui_config, session.registry),
        model=session.config.model,
        resources=session.resources,
        enabled_tools=ui_config.enabled_tools,
        reasoning_effort=session.config.reasoning_effort,
    )
    outcome = controller.dispatch_command(CommandIntent(command))
    if isinstance(outcome, HelpOutcome):
        print(outcome.help_text, file=output)
    elif isinstance(outcome, ToolsOutcome):
        if not outcome.tools:
            print("No tools registered.", file=output)
        else:
            for t in outcome.tools:
                state = "enabled" if t.enabled else "disabled"
                print(f"- {t.name} ({state}): {t.description}", file=output)
    elif isinstance(outcome, SkillsOutcome):
        if outcome.selected_skill is not None:
            s = outcome.selected_skill
            if s.status == "loaded":
                print(f"Skill '{s.name}' ({s.path}):", file=output)
                print(s.content, file=output)
            elif s.status == "registered":
                print(f"Skill '{s.name}' is registered.", file=output)
            elif s.status == "available":
                print(f"Skill '{s.name}' is available but not loaded.", file=output)
            else:
                print(f"Unknown skill: {s.name}", file=error)
        else:
            names = [s.name for s in outcome.skills]
            print("Skills: " + ", ".join(names) if names else "Skills: none", file=output)
    elif isinstance(outcome, SessionInfoOutcome):
        _print_session_info(session, output=output, error=error)
    elif isinstance(outcome, ReasoningOutcome):
        if not outcome.supported:
            print("Reasoning effort is not supported by this provider.", file=output)
        elif outcome.updated and outcome.current is not None:
            print(f"Reasoning effort set to {outcome.current}.", file=output)
    elif isinstance(outcome, CommandErrorOutcome):
        print(f"peon: {outcome.error}", file=error)

    return True


def _handle_command(
    command: str,
    session: TuiSession,
    *,
    provider_factory: ProviderFactory | None,
    input_fn: InputFunction,
    secret_input: SecretInputFunction,
    output: TextIO,
    error: TextIO,
    config_store: ProviderConfigStore,
    ) -> tuple[TuiSession, bool]:
    command_name = command.split(maxsplit=1)[0].lower()
    if _dispatch_tui_controller_command(
        command,
        session,
        output=output,
        error=error,
        config_store=config_store,
    ):
        return session, False
    invocation = DEFAULT_COMMAND_CATALOG.resolve(command)
    if invocation is None:
        print(f"peon: unknown command '{command_name}'; type /help", file=error)
        return session, False
    definition = invocation.command
    if definition.setting_key is not None:
        return (
            _update_active_provider_setting(
                session,
                definition,
                invocation.argument,
                provider_factory=provider_factory,
                input_fn=input_fn,
                secret_input=secret_input,
                output=output,
                error=error,
                config_store=config_store,
            ),
            False,
        )
    if definition.availability == "reserved":
        print(
            f"{definition.name} is reserved and is not available yet.",
            file=output,
        )
        return session, False
    if definition.id == "quit":
        print("Goodbye.", file=output)
        return session, True
    if definition.id == "logout":
        configs = config_store.load_all()
        selected = _select_saved_provider(
            configs,
            input_fn=input_fn,
            output=output,
            error=error,
        )
        if selected is None:
            return session, False
        try:
            config_store.delete(selected)
        except OSError as caught:
            print(f"peon: could not remove saved provider: {caught}", file=error)
            return session, False
        print(f"Saved provider removed: {selected.name}.", file=output)
        remaining = config_store.load_all()
        if not remaining:
            replacement = _configure_session(
                provider_factory=provider_factory,
                input_fn=input_fn,
                secret_input=secret_input,
                output=output,
                error=error,
                context=session.context,
                registry=session.registry,
                resources=session.resources,
                config_store=config_store,
                session_id=session.session_id,
                session_store=session.session_store,
            )
            return replacement or session, False
        if selected != session.config:
            return session, False
        replacement_config = remaining[0]
        try:
            replacement_provider = (provider_factory or create_provider)(
                replacement_config
            )
        except (CommandError, ProviderError, ValueError) as caught:
            print(f"peon: {caught}", file=error)
            return session, False
        print(
            f"Using saved provider: {replacement_config.name} "
            f"({replacement_config.model}).",
            file=output,
        )
        replacement = TuiSession(
            provider=replacement_provider,
            config=replacement_config,
            context=session.context,
            registry=session.registry,
            resources=session.resources,
            session_id=session.session_id,
            session_store=session.session_store,
            persisted_message_count=session.persisted_message_count,
        )
        return replacement, False
    if definition.id == "model":
        selection = invocation.argument
        choices = saved_model_choices(config_store.load_all())
        if not choices:
            _print_saved_models(choices, output=output)
            return session, False
        if command_name == "/models" and not selection:
            _print_saved_models(choices, output=output)
            return session, False
        if not selection:
            _print_saved_models(choices, output=output)
            selection = input_fn("Model: ").strip()
        try:
            selected_model = select_saved_model(selection, choices)
        except CommandError as caught:
            print(f"peon: {caught}", file=error)
            return session, False
        return (
            _switch_model(
                session,
                selection=selected_model,
                provider_factory=provider_factory,
                output=output,
                error=error,
                config_store=config_store,
            ),
            False,
        )
    if definition.id == "new":
        if not any(message.role == "user" for message in session.context.messages):
            discard_empty_session(session.session_store, session.session_id)
        try:
            created = create_session(
                session.session_store,
                parent_id=session.session_id,
            )
        except (OSError, SessionStoreError) as caught:
            print(f"peon: could not start a new conversation: {caught}", file=error)
            return session, False
        context = AgentContext()
        if session.resources is not None:
            apply_resource_prompt(context, session.resources)
        session = replace(
            session,
            context=context,
            session_id=created.session_id,
            persisted_message_count=len(context.messages),
            usage=None,
        )
        print("Conversation cleared.", file=output)
        return session, False
    if definition.id == "session":
        _print_session_info(session, output=output, error=error)
        return session, False
    if definition.id == "resume":
        ui_config = load_ui_config(config_store)
        selected_session = _select_session_for_tui(
            session.session_store,
            argument=invocation.argument,
            input_fn=input_fn,
            output=output,
            error=error,
            delimiter=ui_config.session_list_delimiter,
            current_session_id=session.session_id,
        )
        if selected_session is None:
            return session, False
        session = _open_session(session, selected_session)
        print(
            f"Resumed session: {format_session_summary(selected_session, delimiter=ui_config.session_list_delimiter)}",
            file=output,
        )
        return session, False
    if definition.id == "fork":
        name = invocation.argument or input_fn("Fork name (blank for unnamed): ").strip()
        try:
            session = _fork_session(session, name=name or None)
        except (OSError, SessionStoreError) as caught:
            print(f"peon: could not fork conversation: {caught}", file=error)
            return session, False
        print(f"Forked conversation: {session.session_id}", file=output)
        return session, False
    if definition.id == "provider":
        replacement = _configure_session(
            provider_factory=provider_factory,
            input_fn=input_fn,
            secret_input=secret_input,
            output=output,
            error=error,
            context=session.context,
            registry=session.registry,
            resources=session.resources,
            config_store=config_store,
            session_id=session.session_id,
            session_store=session.session_store,
            persisted_message_count=session.persisted_message_count,
        )
        return replacement or session, False
    if definition.id == "settings":
        return (
            _configure_settings(
                session,
                provider_factory=provider_factory,
                input_fn=input_fn,
                secret_input=secret_input,
                output=output,
                error=error,
                config_store=config_store,
            ),
            False,
        )
    return session, False
