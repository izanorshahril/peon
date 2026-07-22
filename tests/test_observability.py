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
from peon.app.coding_session import CodingSession, MessageEvent, TurnStartedEvent
from peon.app.observability import JsonlTraceSink, serialize_event
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


def test_file_event_journal_sink_writes_schema_v2_events() -> None:
    from peon.app.observability import FileEventJournalSink
    from peon.app.coding_session import TurnStartedEvent

    output = StringIO()
    sink = FileEventJournalSink(output)

    event = TurnStartedEvent(
        session_id="session-1",
        run_id="run-1",
        turn_id="turn-1",
        started_at=100.0,
    )
    sink.write_event(event)

    records = [json.loads(line) for line in output.getvalue().splitlines()]
    assert len(records) == 1
    assert records[0]["schema_version"] == 2
    assert records[0]["event_type"] == "turn_started"
    assert records[0]["session_id"] == "session-1"


def test_shared_serializer_supports_schema_versions_and_event_metadata() -> None:
    event = TurnStartedEvent(
        session_id="session-1",
        run_id="run-1",
        turn_id="turn-1",
        started_at=100.0,
        timestamp=datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc),
        sequence=3,
    )

    schema_one = serialize_event(event, schema_version=1)
    assert schema_one == {
        "schema_version": 1,
        "type": "turn_start",
        "session_id": "session-1",
        "run_id": "run-1",
        "turn_id": "turn-1",
        "started_at": 100.0,
    }

    schema_two = serialize_event(event, schema_version=2)
    assert schema_two["schema_version"] == 2
    assert schema_two["event_type"] == "turn_started"
    assert schema_two["timestamp"] == "2026-07-22T12:00:00+00:00"
    assert schema_two["sequence"] == 3


def test_shared_serializer_rejects_unknown_events_in_strict_mode() -> None:
    with pytest.raises(TypeError, match="unsupported runtime event"):
        serialize_event(object(), strict=True)


def test_shared_serializer_handles_unknown_records_by_policy() -> None:
    record = {"type": "future_event", "value": "ignored"}

    diagnostic = serialize_event(record, schema_version=2)
    assert diagnostic == {
        "schema_version": 2,
        "event_type": "diagnostic",
        "message": "unsupported runtime event: future_event",
    }
    with pytest.raises(TypeError, match="future_event"):
        serialize_event(record, schema_version=1, strict=True)


def test_session_events_receive_ordered_metadata_from_emitter() -> None:
    store = MemorySessionStore()
    record = store.create()
    events: list[object] = []
    session = CodingSession(
        provider=FakeProvider(),
        session_store=store,
        session_id=record.session_id,
        run_id="run-1",
        on_event=events.append,
        event_utc_clock=lambda: datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc),
        id_factory=lambda: "turn-1",
    )

    session.prompt("hello")

    assert [getattr(event, "sequence") for event in events] == list(
        range(len(events))
    )
    assert all(
        getattr(event, "timestamp")
        == datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
        for event in events
    )
    assert isinstance(events[1], MessageEvent)


def test_file_event_journal_sink_applies_redaction_hook() -> None:
    from peon.app.observability import FileEventJournalSink
    from peon.app.coding_session import MessageEvent

    output = StringIO()

    def redact_secret(evt: object) -> object:
        if isinstance(evt, MessageEvent):
            return MessageEvent(
                session_id=evt.session_id,
                run_id=evt.run_id,
                turn_id=evt.turn_id,
                message=AgentMessage(role=evt.message.role, content="[REDACTED]"),
            )
        return evt

    sink = FileEventJournalSink(output, redaction_hook=redact_secret)
    event = MessageEvent(
        session_id="session-1",
        run_id="run-1",
        turn_id="turn-1",
        message=AgentMessage(role="user", content="my secret password is 12345"),
    )
    sink.write_event(event)

    records = [json.loads(line) for line in output.getvalue().splitlines()]
    assert records[0]["message"]["content"] == "[REDACTED]"
    assert "12345" not in output.getvalue()


def test_file_event_journal_sink_handles_strict_and_non_strict_failures() -> None:
    from peon.app.observability import FileEventJournalSink, JournalWriteError
    from peon.app.coding_session import TurnStartedEvent

    class FailingIO(StringIO):
        def write(self, s: str) -> int:
            raise OSError("disk full")

    event = TurnStartedEvent(
        session_id="s1", run_id="r1", turn_id="t1", started_at=1.0
    )

    # Non-strict failure (logs warning, does not raise)
    non_strict_sink = FileEventJournalSink(FailingIO(), strict=False)
    non_strict_sink.write_event(event)

    # Strict failure (raises JournalWriteError)
    strict_sink = FileEventJournalSink(FailingIO(), strict=True)
    with pytest.raises(JournalWriteError, match="disk full"):
        strict_sink.write_event(event)


def test_file_event_journal_sink_strictly_rejects_unknown_records() -> None:
    from peon.app.observability import FileEventJournalSink, JournalWriteError

    with pytest.raises(JournalWriteError, match="future_event"):
        FileEventJournalSink(StringIO(), strict=True).write_event(
            {"type": "future_event"}
        )


def test_coding_session_integrates_event_journal_separate_from_canonical_history() -> None:
    from peon.app.observability import FileEventJournalSink

    output = StringIO()
    journal_sink = FileEventJournalSink(output)
    store = MemorySessionStore()
    record = store.create()

    session = CodingSession(
        provider=FakeProvider(),
        session_store=store,
        session_id=record.session_id,
        journal_sink=journal_sink,
    )

    result = session.prompt("hello journal")
    assert result.status == "success"

    # Journal has schema_version 2 events
    records = [json.loads(line) for line in output.getvalue().splitlines()]
    assert len(records) >= 2
    assert all(r["schema_version"] == 2 for r in records)

    # Canonical message store has canonical messages only
    messages = store.load(session.session_id).messages
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"
