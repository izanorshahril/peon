"""Interactive terminal session for Peon."""

from __future__ import annotations

import getpass
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TextIO

from peon.agent import AgentContext, AgentError, ModelProvider, ToolCall, run_task
from peon.ai import ProviderError
from peon.extensions import ExtensionRegistry, register_sample_tools

from .cli import CommandError, ProviderConfig, ProviderFactory, create_provider

InputFunction = Callable[[str], str]
SecretInputFunction = Callable[[str], str]

_DEFAULT_MODEL = "gpt-4o"
_DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


@dataclass(slots=True)
class TuiSession:
    provider: ModelProvider
    config: ProviderConfig
    context: AgentContext = field(default_factory=AgentContext)
    registry: ExtensionRegistry = field(default_factory=ExtensionRegistry)


def run_tui(
    *,
    provider_factory: ProviderFactory | None = None,
    input_fn: InputFunction = input,
    secret_input: SecretInputFunction | None = None,
    output: TextIO | None = None,
    error: TextIO | None = None,
    registry: ExtensionRegistry | None = None,
) -> int:
    """Run an interactive Peon conversation until the user exits."""
    output = output or sys.stdout
    error = error or sys.stderr
    secret_input = secret_input or getpass.getpass
    active_registry = registry or ExtensionRegistry()
    if registry is None:
        register_sample_tools(active_registry)

    print("Peon interactive mode. Type /help for commands.", file=output)
    session: TuiSession | None = None
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
            )
        return _conversation_loop(
            session,
            provider_factory=provider_factory,
            input_fn=input_fn,
            secret_input=secret_input,
            output=output,
            error=error,
        )
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
) -> TuiSession | None:
    provider_name = input_fn(
        "Provider [openai-compatible/github-copilot] (default: openai-compatible): "
    ).strip().lower()
    provider_name = provider_name or "openai-compatible"
    if provider_name not in {"openai-compatible", "github-copilot"}:
        print(
            "peon: provider must be 'openai-compatible' or 'github-copilot'",
            file=error,
        )
        return None

    model = input_fn(f"Model (default: {_DEFAULT_MODEL}): ").strip()
    model = model or _DEFAULT_MODEL
    if provider_name == "openai-compatible":
        base_url = input_fn(
            f"Base URL (default: {_DEFAULT_OPENAI_BASE_URL}): "
        ).strip()
        base_url = base_url or _DEFAULT_OPENAI_BASE_URL
        api_key = secret_input("API key: ").strip()
        config = ProviderConfig(
            name=provider_name,
            model=model,
            base_url=base_url,
            api_key=api_key,
        )
    else:
        token = secret_input(
            "Copilot token (leave blank to use GITHUB_COPILOT_TOKEN): "
        ).strip()
        config = ProviderConfig(
            name=provider_name,
            model=model,
            copilot_token=token or None,
        )

    try:
        provider = (provider_factory or create_provider)(config)
    except (CommandError, ProviderError, ValueError) as caught:
        print(f"peon: {caught}", file=error)
        return None

    print(f"Provider configured: {config.name} ({config.model})", file=output)
    return TuiSession(
        provider=provider,
        config=config,
        context=context,
        registry=registry,
    )


def _conversation_loop(
    session: TuiSession,
    *,
    provider_factory: ProviderFactory | None,
    input_fn: InputFunction,
    secret_input: SecretInputFunction,
    output: TextIO,
    error: TextIO,
) -> int:
    while True:
        task = input_fn("you> ").strip()
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
            )
            if should_exit:
                return 0
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
) -> tuple[TuiSession, bool]:
    command_name = command.split(maxsplit=1)[0].lower()
    if command_name == "/quit":
        print("Goodbye.", file=output)
        return session, True
    if command_name == "/help":
        print(
            "/provider  configure a provider\n"
            "/tools     list registered tools\n"
            "/clear     clear conversation context\n"
            "/help      show these commands\n"
            "/quit      exit Peon",
            file=output,
        )
        return session, False
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
        )
        return replacement or session, False

    print(f"peon: unknown command '{command_name}'; type /help", file=error)
    return session, False