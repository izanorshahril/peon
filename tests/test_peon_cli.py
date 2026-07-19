from dataclasses import dataclass
from io import StringIO
from typing import Sequence

import pytest

from peon.agent import AgentMessage, ModelResponse, ToolDefinition
from peon.app import ProviderConfig, main


@dataclass
class FakeProvider:
    response: str
    received_messages: tuple[AgentMessage, ...] = ()

    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        self.received_messages = tuple(messages)
        return ModelResponse(content=self.response)


def test_command_runs_task_through_injected_provider_factory() -> None:
    provider = FakeProvider(response="Repository summarized.")
    configurations: list[ProviderConfig] = []

    def provider_factory(config: ProviderConfig) -> FakeProvider:
        configurations.append(config)
        return provider

    output = StringIO()
    error = StringIO()

    result = main(
        ["Summarize the repository.", "--provider", "fake", "--model", "small"],
        provider_factory=provider_factory,
        output=output,
        error=error,
    )

    assert result == 0
    assert output.getvalue() == "Repository summarized.\n"
    assert error.getvalue() == ""
    assert configurations == [ProviderConfig(name="fake", model="small")]
    assert provider.received_messages == (
        AgentMessage(role="user", content="Summarize the repository."),
    )


def test_command_forwards_tool_prompt_role() -> None:
    provider = FakeProvider(response="Done.")
    configurations: list[ProviderConfig] = []

    def provider_factory(config: ProviderConfig) -> FakeProvider:
        configurations.append(config)
        return provider

    result = main(
        [
            "Use a tool.",
            "--provider",
            "custom",
            "--tool-prompt-role",
            "system",
        ],
        provider_factory=provider_factory,
    )

    assert result == 0
    assert configurations[0].tool_prompt_role == "system"


def test_command_reports_missing_task_without_traceback() -> None:
    calls: list[dict[str, object]] = []

    def tui_runner(**kwargs) -> int:
        calls.append(kwargs)
        return 0

    result = main([], tui_runner=tui_runner)

    assert result == 0
    assert len(calls) == 1


def test_command_supports_explicit_tui_flag() -> None:
    calls: list[dict[str, object]] = []

    def tui_runner(**kwargs) -> int:
        calls.append(kwargs)
        return 0

    result = main(["--tui"], tui_runner=tui_runner)

    assert result == 0
    assert len(calls) == 1


def test_command_passes_tui_transcript_layout_options() -> None:
    calls: list[dict[str, object]] = []

    def tui_runner(**kwargs) -> int:
        calls.append(kwargs)
        return 0

    result = main(
        [
            "--tui",
            "--user-top-blank-lines",
            "2",
            "--user-bottom-blank-lines",
            "3",
            "--message-left-padding",
            "4",
        ],
        tui_runner=tui_runner,
    )

    assert result == 0
    assert calls[0]["user_top_blank_lines"] == 2
    assert calls[0]["user_bottom_blank_lines"] == 3
    assert calls[0]["message_left_padding"] == 4


def test_command_forwards_session_lifecycle_options_to_tui() -> None:
    calls: list[dict[str, object]] = []

    def tui_runner(**kwargs) -> int:
        calls.append(kwargs)
        return 0

    result = main(["--tui", "-c"], tui_runner=tui_runner)

    assert result == 0
    assert calls[0]["continue_session"] is True
    assert calls[0]["no_session"] is False

    result = main(["--tui", "--no-session"], tui_runner=tui_runner)

    assert result == 0
    assert calls[1]["continue_session"] is False
    assert calls[1]["no_session"] is True


def test_command_rejects_conflicting_session_lifecycle_options() -> None:
    error = StringIO()

    result = main(["--tui", "--continue", "--no-session"], error=error)

    assert result == 1
    assert "cannot be combined" in error.getvalue()


def test_command_rejects_session_lifecycle_options_for_tasks() -> None:
    error = StringIO()

    result = main(
        ["Do work.", "--continue", "--provider", "fake"],
        error=error,
    )

    assert result == 1
    assert "require interactive mode" in error.getvalue()


def test_command_supports_explicit_interactive_modes() -> None:
    calls: list[dict[str, object]] = []

    def tui_runner(**kwargs) -> int:
        calls.append(kwargs)
        return 0

    result = main(["--mode", "minimal"], tui_runner=tui_runner)

    assert result == 0
    assert len(calls) == 1


def test_command_requires_task_for_non_interactive_mode() -> None:
    error = StringIO()

    result = main(["--mode", "non-interactive"], error=error)

    assert result == 1
    assert "task is required" in error.getvalue()


@pytest.mark.parametrize("mode", ["fullscreen", "webapp"])
def test_command_reports_reserved_modes_as_unavailable(mode: str) -> None:
    error = StringIO()

    result = main(["--mode", mode], error=error)

    assert result == 1
    assert f"{mode} mode is not available yet" in error.getvalue()


def test_command_rejects_task_with_tui_flag() -> None:
    error = StringIO()

    result = main(["Do work.", "--tui"], error=error)

    assert result == 1
    assert "does not accept a task" in error.getvalue()


def test_command_reports_missing_provider_without_traceback() -> None:
    error = StringIO()

    result = main(["Do work."], error=error)

    assert result == 1
    assert "provider is not configured" in error.getvalue()


def test_command_reports_provider_configuration_failure_without_traceback() -> None:
    error = StringIO()

    result = main(
        [
            "Do work.",
            "--provider",
            "openai-compatible",
        ],
        error=error,
    )

    assert result == 1
    assert "requires --base-url" in error.getvalue()