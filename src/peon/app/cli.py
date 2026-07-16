"""Command boundary for running a minimal Peon task."""

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TextIO

from peon.agent import AgentError, ModelProvider, run_task


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    name: str
    model: str | None = None


ProviderFactory = Callable[[ProviderConfig], ModelProvider]


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
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    provider_factory: ProviderFactory | None = None,
    output: TextIO | None = None,
    error: TextIO | None = None,
) -> int:
    output = output or sys.stdout
    error = error or sys.stderr
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        task = " ".join(args.task).strip()
        if not task:
            raise CommandError("task is required")
        if not args.provider:
            raise CommandError("provider is not configured")

        config = ProviderConfig(name=args.provider, model=args.model)
        provider = (provider_factory or create_provider)(config)
        response = run_task(task, provider, model=config.model)
    except (AgentError, CommandError, ValueError) as caught:
        print(f"{parser.prog}: {caught}", file=error)
        return 1

    print(response, file=output)
    return 0


def create_provider(config: ProviderConfig) -> ModelProvider:
    """Create a configured provider once an adapter is installed."""
    raise CommandError(
        f"provider adapter '{config.name}' is not available"
    )