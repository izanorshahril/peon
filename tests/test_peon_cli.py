from dataclasses import dataclass
import json
from io import StringIO
from pathlib import Path
from typing import Sequence

import pytest

from peon.agent import (
    AgentMessage,
    ModelProvider,
    ModelResponse,
    ToolCall,
    ToolDefinition,
    Usage,
)
from peon.app import ProviderConfig, main
from peon.app.sessions import MemorySessionStore, SessionStoreError
from peon.ai import ProviderError
from peon.extensions import ExtensionRegistry


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
        [
            "Summarize the repository.",
            "--provider",
            "fake",
            "--model",
            "small",
            "--no-context-files",
            "--no-skills",
        ],
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
        [
            "-p",
            "Summarize this input.",
            "--provider",
            "fake",
            "--no-context-files",
            "--no-skills",
        ],
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


def test_print_mode_can_write_opt_in_metadata_trace(tmp_path: Path) -> None:
    provider = FakeProvider(response="Repository summarized.")
    output = StringIO()
    trace_path = tmp_path / "trace.jsonl"

    result = main(
        [
            "-p",
            "Do not trace this prompt.",
            "--provider",
            "fake",
            "--trace",
            str(trace_path),
            "--no-context-files",
            "--no-skills",
        ],
        provider_factory=lambda _config: provider,
        output=output,
        error=StringIO(),
    )

    assert result == 0
    assert output.getvalue() == "Repository summarized.\n"
    trace_text = trace_path.read_text(encoding="utf-8")
    assert '"operation":"provider.request"' in trace_text
    assert '"operation":"turn"' in trace_text
    assert "Do not trace this prompt." not in trace_text


def test_print_mode_does_not_decorate_response_with_usage() -> None:
    provider = FakeProvider(
        response=ModelResponse(
            content="Repository summarized.",
            usage=Usage(input_tokens=10, output_tokens=4),
        )
    )
    output = StringIO()

    result = main(
        ["-p", "Summarize the repository.", "--provider", "fake"],
        provider_factory=lambda _config: provider,
        output=output,
        error=StringIO(),
    )

    assert result == 0
    assert output.getvalue() == "Repository summarized.\n"


def test_print_mode_accepts_piped_input_without_a_prompt() -> None:
    provider = FakeProvider(response="Summarized.")

    result = main(
        ["-p", "--provider", "fake", "--no-context-files", "--no-skills"],
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
        [
            "-p",
            "Continue this.",
            "--provider",
            "fake",
            "--continue",
            "--no-context-files",
            "--no-skills",
        ],
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
        [
            "-p",
            "Reopen this.",
            "--provider",
            "fake",
            "--session",
            "release",
            "--no-context-files",
            "--no-skills",
        ],
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


def test_command_forwards_explicit_system_prompt_to_provider() -> None:
    provider = FakeProvider(response="Ready.")

    result = main(
        [
            "Inspect the task.",
            "--provider",
            "fake",
            "--system-prompt",
            "Use concise answers.",
            "--no-context-files",
            "--no-skills",
        ],
        provider_factory=lambda _config: provider,
        output=StringIO(),
        error=StringIO(),
    )

    assert result == 0
    assert provider.received_messages[0] == AgentMessage(
        role="system",
        content="Use concise answers.",
    )


def test_command_loads_discovered_resources_before_provider_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "SYSTEM.md").write_text("Project rules", encoding="utf-8")
    provider = FakeProvider(response="Ready.")

    result = main(
        [
            "Inspect the task.",
            "--provider",
            "fake",
            "--no-skills",
        ],
        provider_factory=lambda _config: provider,
        output=StringIO(),
        error=StringIO(),
    )

    assert result == 0
    assert provider.received_messages[0] == AgentMessage(
        role="system",
        content="Project rules",
    )


def test_print_mode_does_not_persist_generated_resource_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "SYSTEM.md").write_text("Project rules", encoding="utf-8")
    provider = FakeProvider(response="Saved.")
    session_store = MemorySessionStore()

    result = main(
        [
            "Save this request.",
            "--print",
            "--provider",
            "fake",
            "--session-name",
            "release",
            "--no-skills",
        ],
        provider_factory=lambda _config: provider,
        session_store=session_store,
        output=StringIO(),
        error=StringIO(),
    )

    assert result == 0
    saved = session_store.load_latest()
    assert saved is not None
    assert saved.messages == (
        AgentMessage(role="user", content="Save this request."),
        AgentMessage(role="assistant", content="Saved."),
    )
    assert provider.received_messages[0] == AgentMessage(
        role="system",
        content="Project rules",
    )


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
    assert all(event["schema_version"] == 1 for event in events)
    assert events[0]["run_id"]
    assert events[1]["session_id"] == events[0]["session_id"]
    assert events[1]["run_id"] == events[0]["run_id"]
    assert events[1]["turn_id"]
    assert events[4]["session_id"] == events[1]["session_id"]
    assert events[4]["run_id"] == events[1]["run_id"]
    assert events[4]["turn_id"] == events[1]["turn_id"]
    assert events[4]["status"] == "success"
    assert events[2]["content"] == "I checked the request."
    assert events[3]["content"] == "Done."
    assert error.getvalue() == ""


def test_print_event_mode_serializes_normalized_usage() -> None:
    provider = FakeProvider(
        response=ModelResponse(
            content="Done.",
            usage=Usage(
                input_tokens=120,
                output_tokens=30,
                cache_tokens=80,
                cost=0.0042,
                currency="USD",
            ),
        )
    )
    output = StringIO()

    result = main(
        ["-p", "Do work.", "--events", "--provider", "fake"],
        provider_factory=lambda _config: provider,
        output=output,
        error=StringIO(),
    )

    assert result == 0
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    assert events[-2]["type"] == "turn_end"
    assert events[-2]["usage"] == {
        "input_tokens": 120,
        "output_tokens": 30,
        "cache_tokens": 80,
        "cost": 0.0042,
        "currency": "USD",
    }


def test_print_event_mode_uses_injected_correlation_ids_and_clock() -> None:
    output = StringIO()

    result = main(
        ["-p", "Do work.", "--events", "--provider", "fake"],
        provider_factory=lambda _config: FakeProvider(response="Done."),
        run_id_factory=lambda: "run-1",
        turn_id_factory=lambda: "turn-1",
        clock=iter((10.0, 12.5)).__next__,
        output=output,
        error=StringIO(),
    )

    assert result == 0
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    assert all(event["run_id"] == "run-1" for event in events)
    assert events[1]["turn_id"] == "turn-1"
    assert events[3]["duration"] == 2.5


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
    turn_events = events[1:6]
    assert all(event["session_id"] == events[0]["session_id"] for event in turn_events)
    assert all(event["run_id"] == events[0]["run_id"] for event in turn_events)
    assert len({event["turn_id"] for event in turn_events}) == 1
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


def test_print_event_mode_reports_runtime_failure_as_one_correlated_terminal_error() -> None:
    output = StringIO()
    provider = FakeProvider(response=ModelResponse())

    result = main(
        ["-p", "Do work.", "--events", "--provider", "fake"],
        provider_factory=lambda _config: provider,
        output=output,
        error=StringIO(),
    )

    assert result == 1
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [event["type"] for event in events] == [
        "session_start",
        "user",
        "error",
        "session_end",
    ]
    assert events[2]["status"] == "error"
    assert events[2]["message"] == "provider returned an empty response"
    assert events[2]["session_id"] == events[0]["session_id"]
    assert events[2]["run_id"] == events[0]["run_id"]
    assert events[2]["turn_id"]
    assert events[3]["status"] == "error"


def test_print_event_mode_serializes_resource_failure_as_session_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "peon.app.cli._load_resources",
        lambda _args: (_ for _ in ()).throw(OSError("resource unavailable")),
    )
    output = StringIO()

    result = main(
        ["-p", "Do work.", "--events", "--provider", "fake"],
        provider_factory=lambda _config: FakeProvider(response="Done."),
        output=output,
        error=StringIO(),
    )

    assert result == 1
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [event["type"] for event in events] == [
        "session_start",
        "error",
        "session_end",
    ]
    assert events[1]["message"] == "resource unavailable"
    assert events[1]["status"] == "error"
    assert events[2]["success"] is False


def test_print_event_mode_serializes_tool_failure_as_one_terminal_error() -> None:
    registry = ExtensionRegistry()
    registry.register_tool(
        name="fail",
        description="Fail.",
        parameters={},
        handler=lambda _arguments: (_ for _ in ()).throw(ValueError("bad tool")),
    )
    provider = ScriptedProvider(
        responses=[
            ModelResponse(
                tool_call=ToolCall(
                    name="fail",
                    arguments={},
                    call_id="call-1",
                )
            )
        ]
    )
    output = StringIO()

    result = main(
        ["-p", "Use the tool.", "--events", "--provider", "fake"],
        provider_factory=lambda _config: provider,
        registry=registry,
        output=output,
        error=StringIO(),
    )

    assert result == 1
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [event["type"] for event in events] == [
        "session_start",
        "user",
        "tool_call",
        "tool_result",
        "error",
        "session_end",
    ]
    assert events[4]["status"] == "error"
    assert "tool 'fail' failed: bad tool" in events[4]["message"]
    assert events[4]["turn_id"] == events[2]["turn_id"]


class FailingAppendStore(MemorySessionStore):
    def append(self, session_id: str, message: AgentMessage) -> None:
        raise SessionStoreError("persistence unavailable")


def test_print_event_mode_serializes_persistence_failure_as_one_terminal_error() -> None:
    output = StringIO()

    result = main(
        [
            "Persist this.",
            "--print",
            "--events",
            "--provider",
            "fake",
            "--session-name",
            "release",
        ],
        provider_factory=lambda _config: FakeProvider(response="Saved."),
        session_store=FailingAppendStore(),
        output=output,
        error=StringIO(),
    )

    assert result == 1
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [event["type"] for event in events] == [
        "session_start",
        "error",
        "session_end",
    ]
    assert events[1]["status"] == "error"
    assert "persistence unavailable" in events[1]["message"]
    assert events[2]["success"] is False


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
    assert calls[0]["host_id"] == "textual"


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