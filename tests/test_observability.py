import json
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Sequence

import pytest

from peon.agent import (
    AgentContext,
    AgentMessage,
    ModelResponse,
    ToolCall,
    ToolDefinition,
    ToolExecutionContext,
    TraceContext,
    run_task,
)
from peon.app.coding_session import CodingSession
from peon.app.observability import JsonlTraceSink
from peon.app.resources import ResourceLoader
from peon.app.sessions import MemorySessionStore
from peon.extensions import ExtensionRegistry


class FakeProvider:
    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        return ModelResponse(content="Done.")


class FailingProvider:
    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        raise RuntimeError("provider failure; do not record this text")


class FailingSink:
    def emit(self, record: dict[str, object]) -> None:
        raise OSError("trace destination unavailable")


class CancellationProvider:
    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        return ModelResponse(
            tool_call=ToolCall(name="cancel", arguments={}, call_id="call-1")
        )


class CancellingExecutor:
    tools: tuple[ToolDefinition, ...] = ()

    def invoke(
        self,
        name: str,
        arguments: dict[str, object],
    ) -> str:
        raise AssertionError("context-aware invocation is required")

    def invoke_with_context(
        self,
        name: str,
        arguments: dict[str, object],
        context: ToolExecutionContext,
    ) -> str:
        context.cancel()
        return "cancelled"


def test_coding_session_emits_metadata_only_turn_and_provider_traces() -> None:
    output = StringIO()
    monotonic_values = iter(
        (10.0, 10.1, 10.15, 10.25, 10.5, 10.6, 10.65, 11.0)
    )
    store = MemorySessionStore()
    record = store.create()
    session = CodingSession(
        provider=FakeProvider(),
        session_store=store,
        session_id=record.session_id,
        run_id="run-1",
        model="small-model",
        trace_sink=JsonlTraceSink(output),
        trace_provider="fake-provider",
        clock=lambda: next(monotonic_values),
        trace_utc_clock=lambda: datetime(
            2026, 7, 20, 12, 0, tzinfo=timezone.utc
        ),
        id_factory=lambda: "turn-1",
    )

    result = session.prompt("Do not leak this prompt.")

    assert result.content == "Done."
    records = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [record["operation"] for record in records] == [
        "persistence.append",
        "provider.request",
        "persistence.append",
        "turn",
    ]
    assert records[1] == {
        "schema_version": 1,
        "timestamp": "2026-07-20T12:00:00+00:00",
        "duration": 0.25,
        "session_id": record.session_id,
        "run_id": "run-1",
        "turn_id": "turn-1",
        "operation": "provider.request",
        "outcome": "success",
        "provider": "fake-provider",
        "model": "small-model",
    }
    assert records[0]["duration"] == pytest.approx(0.05)
    assert records[2]["duration"] == pytest.approx(0.05)
    assert records[3]["duration"] == pytest.approx(1.0)
    assert records[3]["operation"] == "turn"
    assert records[3]["outcome"] == "success"
    assert "Do not leak this prompt." not in output.getvalue()


def test_trace_export_failure_does_not_change_successful_turn() -> None:
    store = MemorySessionStore()
    record = store.create()
    session = CodingSession(
        provider=FakeProvider(),
        session_store=store,
        session_id=record.session_id,
        trace_sink=FailingSink(),
        clock=iter(
            (10.0, 10.25, 10.5, 10.55, 10.7, 10.75, 10.9, 11.0)
        ).__next__,
        id_factory=lambda: "turn-1",
    )

    result = session.prompt("keep going")

    assert result.content == "Done."
    assert store.load(record.session_id).messages[-1].content == "Done."


def test_provider_failure_emits_error_metadata_without_failure_content() -> None:
    output = StringIO()
    store = MemorySessionStore()
    record = store.create()
    session = CodingSession(
        provider=FailingProvider(),
        session_store=store,
        session_id=record.session_id,
        run_id="run-1",
        trace_sink=JsonlTraceSink(output),
        trace_provider="fake-provider",
        model="small-model",
        clock=iter((10.0, 10.1, 10.2, 10.3, 10.5, 11.0)).__next__,
        trace_utc_clock=lambda: datetime(
            2026, 7, 20, 12, 0, tzinfo=timezone.utc
        ),
        id_factory=lambda: "turn-1",
    )

    result = session.prompt("Do not record this prompt.")

    assert result.status == "error"
    records = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [record["operation"] for record in records] == [
        "persistence.append",
        "provider.request",
        "turn",
    ]
    assert records[0]["outcome"] == "success"
    assert records[1]["outcome"] == "error"
    assert records[2]["outcome"] == "error"
    assert "provider failure" not in output.getvalue()
    assert "Do not record this prompt." not in output.getvalue()


def test_cancelled_tool_emits_cancelled_metadata() -> None:
    output = StringIO()
    execution_context = ToolExecutionContext()
    clock = iter((1.0, 1.1, 1.2, 1.3)).__next__

    with pytest.raises(Exception, match="tool execution cancelled"):
        run_task(
            "cancel this work",
            CancellationProvider(),
            context=AgentContext(),
            executor=CancellingExecutor(),
            execution_context=execution_context,
            trace_sink=JsonlTraceSink(output),
            trace_context=TraceContext(
                session_id="session-1",
                run_id="run-1",
                turn_id="turn-1",
            ),
            trace_clock=clock,
            trace_utc_clock=lambda: datetime(
                2026, 7, 20, 12, 0, tzinfo=timezone.utc
            ),
        )

    records = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [record["operation"] for record in records] == [
        "provider.request",
        "tool.invoke",
    ]
    assert records[1]["outcome"] == "cancelled"


def test_resource_and_hook_traces_are_metadata_only(tmp_path: Path) -> None:
    output = StringIO()
    clock = iter((1.0, 1.5, 2.0, 2.25)).__next__
    context = TraceContext(
        session_id="session-1",
        run_id="run-1",
        turn_id="turn-1",
    )
    sink = JsonlTraceSink(output)

    ResourceLoader(
        root=tmp_path,
        global_root=tmp_path / "global",
        trace_sink=sink,
        trace_context=context,
        trace_clock=clock,
    ).load()
    registry = ExtensionRegistry(
        trace_sink=sink,
        trace_context=context,
        trace_clock=clock,
    )
    registry.on("startup", lambda: None)
    registry.emit("startup")

    records = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [record["operation"] for record in records] == [
        "resource.load",
        "extension.hook",
    ]
    assert records[0]["duration"] == pytest.approx(0.5)
    assert records[1]["duration"] == pytest.approx(0.25)
    assert records[1]["hook"] == "startup"
    assert "SKILL.md" not in output.getvalue()
    assert "global" not in output.getvalue()
    assert "session-1" in output.getvalue()


def test_disabled_tracing_does_not_call_trace_clock() -> None:
    def fail_if_called() -> float:
        raise AssertionError("disabled tracing called its clock")

    response = run_task(
        "run without tracing",
        FakeProvider(),
        trace_clock=fail_if_called,
    )

    assert response == "Done."
