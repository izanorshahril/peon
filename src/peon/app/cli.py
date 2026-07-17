"""Command boundary for running a minimal Peon task."""

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, TextIO

from peon.agent import AgentError, ModelProvider, ToolCall, run_task
from peon.ai import (
    GitHubCopilotProvider,
    OpenAICompatibleProvider,
    ProviderError,
)


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    name: str
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    copilot_token: str | None = None
    models: tuple[str, ...] = ()


ProviderFactory = Callable[[ProviderConfig], ModelProvider]
InteractionMode = Literal["non-interactive", "minimal", "fullscreen", "webapp"]


class CommandError(Exception):
    """An operator-facing command boundary error."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="peon",
        description="Run a task through the Peon agent core.",
    )
    parser.add_argument("task", nargs="*", help="Task to send to the agent")
    parser.add_argument("--provider", help="Provider adapter name")
    parser.add_argument("--model", help="Provider model name")
    parser.add_argument("--base-url", help="OpenAI-compatible provider base URL")
    parser.add_argument("--api-key", help="OpenAI-compatible provider API key")
    parser.add_argument("--copilot-token", help="GitHub Copilot login token")
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Start an interactive session with in-session provider setup",
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
    output: TextIO | None = None,
    error: TextIO | None = None,
) -> int:
    output = output or sys.stdout
    error = error or sys.stderr
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        task = " ".join(args.task).strip()
        mode: InteractionMode = args.mode or (
            "minimal" if args.tui or not task else "non-interactive"
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
            )
        else:
            raise CommandError(f"{mode} mode is not available yet")
        if not args.provider:
            raise CommandError("provider is not configured")

        config = ProviderConfig(
            name=args.provider,
            model=args.model,
            base_url=args.base_url,
            api_key=args.api_key,
            copilot_token=args.copilot_token,
        )
        provider = (provider_factory or create_provider)(config)
        response = run_task(task, provider, model=config.model)
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


def create_provider(config: ProviderConfig) -> ModelProvider:
    """Create a provider adapter from generic command configuration."""
    if config.name == "openai-compatible":
        if config.base_url is None:
            raise CommandError("openai-compatible provider requires --base-url")
        return OpenAICompatibleProvider(
            base_url=config.base_url,
            api_key=config.api_key,
            model=config.model,
        )
    if config.name == "github-copilot":
        return GitHubCopilotProvider(
            token=config.copilot_token,
            model=config.model or "gpt-4o",
        )
    raise CommandError(f"provider adapter '{config.name}' is not available")