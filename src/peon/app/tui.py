"""Interactive terminal session for Peon."""

from __future__ import annotations

import getpass
from pathlib import Path
import shutil
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import TextIO

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion, CompleteEvent
from prompt_toolkit.document import Document

from peon.agent import AgentContext, AgentError, ModelProvider, ToolCall, run_task
from peon.ai import ProviderError
from peon.extensions import ExtensionRegistry, register_sample_tools

from .cli import CommandError, ProviderConfig, ProviderFactory, create_provider
from .config import JsonProviderConfigStore, ProviderConfigStore

InputFunction = Callable[[str], str]
SecretInputFunction = Callable[[str], str]

_DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
_PEON_VERSION = "0.1.0"
_PROVIDER_OPTIONS = (
    ("openai-compatible", "OpenAI-compatible"),
    ("github-copilot", "GitHub Copilot"),
)
_COMMAND_SPECS = (
    ("/help", "show available commands"),
    ("/model", "switch the active model"),
    ("/models", "list saved models"),
    ("/provider", "configure a provider"),
    ("/logout", "remove one saved provider"),
    ("/tools", "list registered tools"),
    ("/clear", "clear conversation context"),
    ("/quit", "exit Peon"),
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
        if not text.startswith("/") or " " in text:
            return
        prefix = text.lower()
        for command, description in _COMMAND_SPECS:
            if command.startswith(prefix):
                yield Completion(
                    command,
                    start_position=-len(text),
                    display=command,
                    display_meta=description,
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


def _terminal_rule() -> str:
    width = shutil.get_terminal_size((80, 24)).columns
    return "─" * max(40, min(width, 120))


def _print_header(*, output: TextIO) -> None:
    print(f" peon v{_PEON_VERSION}", file=output)
    print(
        " escape interrupt · ctrl+c/ctrl+d clear/exit · / commands",
        file=output,
    )
    print(" Type /help for commands and /models for detected models.", file=output)


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
    user_top_blank_lines: int = 1,
    user_bottom_blank_lines: int = 1,
    message_left_padding: int = 1,
) -> int:
    """Run an interactive Peon conversation until the user exits."""
    output = output or sys.stdout
    error = error or sys.stderr
    secret_input = secret_input or getpass.getpass
    active_registry = registry or ExtensionRegistry()
    active_config_store = config_store or JsonProviderConfigStore()
    if registry is None:
        register_sample_tools(active_registry)

    if input_fn is None:
        from .textual_tui import run_textual_tui

        return run_textual_tui(
            provider_factory=provider_factory,
            output=output,
            error=error,
            registry=active_registry,
            config_store=active_config_store,
            user_top_blank_lines=user_top_blank_lines,
            user_bottom_blank_lines=user_bottom_blank_lines,
            message_left_padding=message_left_padding,
        )

    _print_header(output=output)
    session = _restore_session(
        provider_factory=provider_factory,
        config_store=active_config_store,
        input_fn=input_fn,
        output=output,
        error=error,
        context=AgentContext(),
        registry=active_registry,
    )
    try:
        while session is None:
            session = _configure_session(
                provider_factory=provider_factory,
                input_fn=input_fn,
                secret_input=secret_input,
                output=output,
                error=error,
                context=AgentContext(),
                registry=active_registry,
                config_store=active_config_store,
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
        if provider_name == "openai-compatible":
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
                model=selected_model,
                models=models,
                base_url=config.base_url,
                api_key=config.api_key,
                copilot_token=config.copilot_token,
            )
            provider = (provider_factory or create_provider)(config)
        else:
            config = ProviderConfig(
                name=config.name,
                model="gpt-4o",
                base_url=config.base_url,
                api_key=config.api_key,
                copilot_token=config.copilot_token,
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
    )


def _restore_session(
    *,
    provider_factory: ProviderFactory | None,
    config_store: ProviderConfigStore,
    input_fn: InputFunction,
    output: TextIO,
    error: TextIO,
    context: AgentContext,
    registry: ExtensionRegistry,
) -> TuiSession | None:
    configs = config_store.load_all()
    if not configs:
        return None
    config = _select_saved_provider(configs, input_fn=input_fn, output=output, error=error)
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


def _matching_commands(command_name: str) -> tuple[str, ...]:
    prefix = command_name.lower()
    return tuple(
        command for command, _description in _COMMAND_SPECS if command.startswith(prefix)
    )


def _resolve_command(command_name: str) -> str | None:
    matches = _matching_commands(command_name)
    return matches[0] if matches else None


def _print_models(models: tuple[str, ...], *, output: TextIO) -> None:
    if not models:
        print("No saved models. Use /provider to discover models.", file=output)
        return
    print("Available models:", file=output)
    for index, model in enumerate(models, start=1):
        print(f"  {index}. {model}", file=output)


def _switch_model(
    session: TuiSession,
    *,
    selection: str,
    provider_factory: ProviderFactory | None,
    output: TextIO,
    error: TextIO,
    config_store: ProviderConfigStore,
) -> TuiSession:
    if not session.config.models:
        print("No saved models. Use /provider to discover models.", file=output)
        return session
    try:
        model = _select_model(selection, session.config.models)
        config = ProviderConfig(
            name=session.config.name,
            model=model,
            models=session.config.models,
            base_url=session.config.base_url,
            api_key=session.config.api_key,
            copilot_token=session.config.copilot_token,
        )
        provider = (provider_factory or create_provider)(config)
    except (CommandError, ProviderError, ValueError) as caught:
        print(f"peon: {caught}", file=error)
        return session
    _save_configuration(config_store, config, error=error)
    print(f"Model selected: {model}", file=output)
    return TuiSession(
        provider=provider,
        config=config,
        context=session.context,
        registry=session.registry,
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
            print(f"peon: {caught}", file=error)
            continue
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
    resolved_command = _resolve_command(command_name)
    if resolved_command is None:
        print(f"peon: unknown command '{command_name}'; type /help", file=error)
        return session, False
    command_name = resolved_command
    if command_name == "/quit":
        print("Goodbye.", file=output)
        return session, True
    if command_name == "/help":
        print(
            "/provider  configure a provider\n"
            "/models    list saved models\n"
            "/model     switch the active model\n"
            "/tools     list registered tools\n"
            "/clear     clear conversation context\n"
            "/help      show these commands\n"
            "/quit      exit Peon",
            file=output,
        )
        return session, False
    if command_name == "/models":
        _print_models(session.config.models, output=output)
        return session, False
    if command_name == "/logout":
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
        )
        return replacement, False
    if command_name == "/model":
        parts = command.split(maxsplit=1)
        selection = parts[1].strip() if len(parts) == 2 else ""
        if not selection:
            _print_models(session.config.models, output=output)
            if not session.config.models:
                return session, False
            selection = input_fn("Model: ").strip()
        return (
            _switch_model(
                session,
                selection=selection,
                provider_factory=provider_factory,
                output=output,
                error=error,
                config_store=config_store,
            ),
            False,
        )
    if command_name == "/tools":
        if not session.registry.tools:
            print("No tools registered.", file=output)
        else:
            for tool in session.registry.tools:
                print(f"- {tool.name}: {tool.description}", file=output)
        return session, False
    if command_name == "/clear":
        session.context.messages.clear()
        print("Conversation cleared.", file=output)
        return session, False
    if command_name == "/provider":
        replacement = _configure_session(
            provider_factory=provider_factory,
            input_fn=input_fn,
            secret_input=secret_input,
            output=output,
            error=error,
            context=session.context,
            registry=session.registry,
            config_store=config_store,
        )
        return replacement or session, False
    return session, False
