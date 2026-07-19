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

from peon.agent import AgentContext, AgentError, ModelProvider, ToolCall, run_task
from peon.ai import ProviderError
from peon.extensions import (
    ExtensionRegistry,
    register_filesystem_tools,
    register_sample_tools,
)

from .cli import (
    CONFIG_SETTING_SPECS,
    CommandError,
    ProviderConfig,
    ProviderFactory,
    ProviderSettingSpec,
    REQUEST_FIELD_SETTING_SPECS,
    RESPONSE_FIELD_SETTING_SPECS,
    SavedModel,
    create_provider,
    saved_model_choices,
    select_saved_model,
    update_provider_setting,
)
from .config import (
    UI_SETTING_SPECS,
    JsonProviderConfigStore,
    ProviderConfigStore,
    load_ui_config,
    save_ui_config,
    update_saved_provider,
    update_ui_setting,
)
from .commands import DEFAULT_COMMAND_CATALOG, CommandDefinition
from .sessions import (
    JsonlSessionStore,
    MemorySessionStore,
    SessionStore,
    SessionStoreError,
    create_session,
)

InputFunction = Callable[[str], str]
SecretInputFunction = Callable[[str], str]

_DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
_PEON_VERSION = "0.1.0"
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
    session_id: str = ""
    session_store: SessionStore = field(default_factory=MemorySessionStore)
    persisted_message_count: int = 0


def _terminal_rule() -> str:
    width = shutil.get_terminal_size((80, 24)).columns
    return "─" * max(40, min(width, 120))


def _print_header(*, output: TextIO) -> None:
    print(f" peon v{_PEON_VERSION}", file=output)
    print(
        " escape interrupt · ctrl+c/ctrl+d clear/exit · / commands",
        file=output,
    )
    print(" Type /help for commands and /model for saved models.", file=output)


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
) -> int:
    """Run an interactive Peon conversation until the user exits."""
    output = output or sys.stdout
    error = error or sys.stderr
    secret_input = secret_input or getpass.getpass
    active_registry = registry or ExtensionRegistry()
    active_config_store = config_store or JsonProviderConfigStore()
    active_session_store = session_store or _default_session_store(active_config_store)
    if no_session:
        active_session_store = MemorySessionStore()
    if registry is None:
        register_sample_tools(active_registry)
        register_filesystem_tools(active_registry)

    if input_fn is None:
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
        )

    _print_header(output=output)
    active_session_store, session_id, context = _load_starting_session(
        active_session_store,
        error=error,
        continue_session=continue_session,
    )
    session = _restore_session(
        provider_factory=provider_factory,
        config_store=active_config_store,
        output=output,
        error=error,
        context=context,
        registry=active_registry,
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
        _print_footer(session, output=output)
        return result
    except (EOFError, KeyboardInterrupt):
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
) -> tuple[SessionStore, str, AgentContext]:
    if continue_session:
        try:
            latest = store.load_latest()
        except SessionStoreError as caught:
            print(f"peon: could not resume saved session: {caught}", file=error)
            latest = None
        if latest is not None:
            return store, latest.session_id, AgentContext(messages=list(latest.messages))
    try:
        created = store.create()
    except (OSError, SessionStoreError) as caught:
        print(f"peon: could not create saved session: {caught}", file=error)
        fallback = MemorySessionStore()
        created = fallback.create()
        return fallback, created.session_id, AgentContext()
    return store, created.session_id, AgentContext()


def _configure_session(
    *,
    provider_factory: ProviderFactory | None,
    input_fn: InputFunction,
    secret_input: SecretInputFunction,
    output: TextIO,
    error: TextIO,
    context: AgentContext,
    registry: ExtensionRegistry,
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
            ("config", "Config", CONFIG_SETTING_SPECS),
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
                config_store=config_store,
                session_id=session.session_id,
                session_store=session.session_store,
                persisted_message_count=session.persisted_message_count,
            )
            session = replacement or session
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
        for spec in (*CONFIG_SETTING_SPECS,)
        if spec.key == setting
    ) if setting != "name" else ProviderSettingSpec("name", "Name", "name", "text")
    current = getattr(session.config, spec.field_name)
    value = argument.strip()
    if not value and spec.value_kind == "toggle":
        value = str(not bool(current)).lower()
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
        task = input_fn(" > ").strip()
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

        try:
            response = run_task(
                task,
                session.provider,
                context=session.context,
                executor=session.registry,
                model=session.config.model,
            )
        except AgentError as caught:
            _persist_new_messages(session, error=error)
            print(f"peon: {caught}", file=error)
            continue
        _persist_new_messages(session, error=error)
        if isinstance(response, ToolCall):
            print(
                f"peon: provider requested unhandled tool '{response.name}'",
                file=error,
            )
            continue
        print(f"peon> {response}", file=output)


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
    if definition.id == "help":
        print(DEFAULT_COMMAND_CATALOG.help_text(), file=output)
        return session, False
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
    if definition.id == "tools":
        if not session.registry.tools:
            print("No tools registered.", file=output)
        else:
            for tool in session.registry.tools:
                print(f"- {tool.name}: {tool.description}", file=output)
        return session, False
    if definition.id == "new":
        try:
            created = create_session(
                session.session_store,
                parent_id=session.session_id,
            )
        except (OSError, SessionStoreError) as caught:
            print(f"peon: could not start a new conversation: {caught}", file=error)
            return session, False
        session = replace(
            session,
            context=AgentContext(),
            session_id=created.session_id,
            persisted_message_count=0,
        )
        print("Conversation cleared.", file=output)
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


def _persist_new_messages(
    session: TuiSession,
    *,
    error: TextIO,
) -> None:
    for index in range(session.persisted_message_count, len(session.context.messages)):
        message = session.context.messages[index]
        try:
            session.session_store.append(session.session_id, message)
        except (OSError, SessionStoreError) as caught:
            print(f"peon: could not save conversation: {caught}", file=error)
            return
        session.persisted_message_count = index + 1
