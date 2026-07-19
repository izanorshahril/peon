from dataclasses import dataclass
import json
from io import StringIO
from typing import Sequence

import pytest

from peon.agent import (
    AgentMessage,
    ModelProvider,
    ModelResponse,
    ToolCall,
    ToolDefinition,
)
from peon.app import ProviderConfig, main
from peon.app.sessions import MemorySessionStore
from peon.ai import ProviderError


@dataclass
class FakeProvider:
    response: str | ModelResponse
    received_messages: tuple[AgentMessage, ...] = ()

    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        self.received_messages = tuple(messages)
        if isinstance(self.response, ModelResponse):
            return self.response
        return ModelResponse(content=self.response)


@dataclass
class ScriptedProvider:
    responses: list[ModelResponse]

    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        return self.responses.pop(0)


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


def test_print_mode_writes_only_response_and_includes_piped_input() -> None:
    provider = FakeProvider(response="Repository summarized.")
    output = StringIO()
    error = StringIO()

    result = main(
        ["-p", "Summarize this input.", "--provider", "fake"],
        provider_factory=lambda _config: provider,
        input=StringIO("piped context"),
        output=output,
        error=error,
    )

    assert result == 0
    assert output.getvalue() == "Repository summarized.\n"
    assert error.getvalue() == ""
    assert provider.received_messages == (
        AgentMessage(
            role="user",
            content="Summarize this input.\n\npiped context",
        ),
    )


def test_print_mode_accepts_piped_input_without_a_prompt() -> None:
    provider = FakeProvider(response="Summarized.")

    result = main(
        ["-p", "--provider", "fake"],
        provider_factory=lambda _config: provider,
        input=StringIO("piped context\n"),
        output=StringIO(),
        error=StringIO(),
    )

    assert result == 0
    assert provider.received_messages == (
        AgentMessage(role="user", content="piped context\n"),
    )


def test_print_mode_uses_an_ephemeral_session_by_default() -> None:
    provider = FakeProvider(response="Done.")
    session_store = MemorySessionStore()

    result = main(
        ["-p", "Do work.", "--provider", "fake"],
        provider_factory=lambda _config: provider,
        session_store=session_store,
        output=StringIO(),
        error=StringIO(),
    )

    assert result == 0
    assert session_store.order == []


def test_print_mode_persists_when_an_explicit_session_name_is_given() -> None:
    provider = FakeProvider(response="Saved.")
    session_store = MemorySessionStore()

    result = main(
        [
            "-p",
            "Save this.",
            "--provider",
            "fake",
            "--session-name",
            "release",
        ],
        provider_factory=lambda _config: provider,
        session_store=session_store,
        output=StringIO(),
        error=StringIO(),
    )

    assert result == 0
    saved = session_store.load_latest()
    assert saved is not None
    assert saved.name == "release"
    assert saved.messages == (
        AgentMessage(role="user", content="Save this."),
        AgentMessage(role="assistant", content="Saved."),
    )


def test_print_mode_continues_only_when_explicitly_requested() -> None:
    provider = FakeProvider(response="Continued.")
    session_store = MemorySessionStore()
    previous = session_store.create(name="release")
    session_store.append(previous.session_id, AgentMessage(role="user", content="Old."))

    result = main(
        ["-p", "Continue this.", "--provider", "fake", "--continue"],
        provider_factory=lambda _config: provider,
        session_store=session_store,
        output=StringIO(),
        error=StringIO(),
    )

    assert result == 0
    assert provider.received_messages == (
        AgentMessage(role="user", content="Old."),
        AgentMessage(role="user", content="Continue this."),
    )
    assert len(session_store.order) == 1
    assert session_store.load(previous.session_id).messages[-1] == AgentMessage(
        role="assistant",
        content="Continued.",
    )


def test_print_mode_opens_an_explicit_session_target() -> None:
    provider = FakeProvider(response="Reopened.")
    session_store = MemorySessionStore()
    previous = session_store.create(name="release")
    session_store.append(previous.session_id, AgentMessage(role="user", content="Old."))

    result = main(
        ["-p", "Reopen this.", "--provider", "fake", "--session", "release"],
        provider_factory=lambda _config: provider,
        session_store=session_store,
        output=StringIO(),
        error=StringIO(),
    )

    assert result == 0
    assert provider.received_messages == (
        AgentMessage(role="user", content="Old."),
        AgentMessage(role="user", content="Reopen this."),
    )
    assert len(session_store.order) == 1


def test_print_event_mode_emits_ordered_json_lines() -> None:
    provider = FakeProvider(
        response=ModelResponse(
            content="Done.",
            thinking="I checked the request.",
        )
    )
    output = StringIO()
    error = StringIO()

    result = main(
        ["-p", "Do work.", "--events", "--provider", "fake"],
        provider_factory=lambda _config: provider,
        output=output,
        error=error,
    )

    assert result == 0
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [event["type"] for event in events] == [
        "session_start",
        "user",
        "thinking",
        "assistant",
        "turn_end",
        "session_end",
    ]
    assert events[2]["content"] == "I checked the request."
    assert events[3]["content"] == "Done."
    assert error.getvalue() == ""


def test_print_event_mode_emits_tool_lifecycle_events() -> None:
    provider = ScriptedProvider(
        responses=[
            ModelResponse(
                tool_call=ToolCall(
                    name="word_count",
                    arguments={"text": "one two"},
                    call_id="call-1",
                )
            ),
            ModelResponse(content="There are two words."),
        ]
    )
    output = StringIO()

    result = main(
        ["-p", "Count this.", "--events", "--provider", "fake"],
        provider_factory=lambda _config: provider,
        output=output,
        error=StringIO(),
    )

    assert result == 0
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [event["type"] for event in events] == [
        "session_start",
        "user",
        "tool_call",
        "tool_result",
        "assistant",
        "turn_end",
        "session_end",
    ]
    assert events[2]["call_id"] == "call-1"
    assert events[3]["content"] == "word count: 2"


def test_print_mode_reports_provider_failure_without_output_decoration() -> None:
    output = StringIO()
    error = StringIO()

    result = main(
        ["-p", "Do work.", "--provider", "fake"],
        provider_factory=lambda _config: _raise_provider_error(),
        output=output,
        error=error,
    )

    assert result == 1
    assert output.getvalue() == ""
    assert error.getvalue() == "peon: provider unavailable\n"


def test_print_event_mode_reports_provider_failure_as_json() -> None:
    output = StringIO()
    error = StringIO()

    result = main(
        ["-p", "Do work.", "--events", "--provider", "fake"],
        provider_factory=lambda _config: _raise_provider_error(),
        output=output,
        error=error,
    )

    assert result == 1
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [event["type"] for event in events] == [
        "session_start",
        "error",
        "session_end",
    ]
    assert events[1]["message"] == "provider unavailable"
    assert events[2]["session_id"] == events[0]["session_id"]
    assert error.getvalue() == ""


def test_events_require_print_mode() -> None:
    error = StringIO()

    result = main(["--events", "--provider", "fake"], error=error)

    assert result == 1
    assert "--events requires --print" in error.getvalue()


def test_print_mode_rejects_interactive_flags() -> None:
    error = StringIO()

    result = main(["-p", "Do work.", "--tui"], error=error)

    assert result == 1
    assert "--print cannot be combined with interactive mode" in error.getvalue()


@pytest.mark.parametrize("mode", ["minimal", "fullscreen", "webapp"])
def test_print_mode_rejects_explicit_interaction_modes(mode: str) -> None:
    error = StringIO()

    result = main(["-p", "Do work.", "--mode", mode], error=error)

    assert result == 1
    assert "--print cannot be combined with interactive mode" in error.getvalue()


def _raise_provider_error() -> ModelProvider:
    raise ProviderError("provider unavailable")


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

    result = main(
        ["--tui", "--session", "release", "--session-name", "ignored"],
        tui_runner=tui_runner,
    )

    assert result == 1


def test_command_forwards_session_target_and_name_to_tui() -> None:
    calls: list[dict[str, object]] = []

    def tui_runner(**kwargs) -> int:
        calls.append(kwargs)
        return 0

    result = main(
        ["--tui", "--session-name", "release"],
        tui_runner=tui_runner,
    )

    assert result == 0
    assert calls[0]["session_target"] is None
    assert calls[0]["session_name"] == "release"

    result = main(
        ["--tui", "--session", "session-id"],
        tui_runner=tui_runner,
    )

    assert result == 0
    assert calls[1]["session_target"] == "session-id"
    assert calls[1]["session_name"] is None


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