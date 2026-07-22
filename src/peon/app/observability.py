"""Application-owned performance trace sinks and event journaling."""

from collections.abc import Callable, Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime
import json
import logging
from pathlib import Path
from threading import Lock
from typing import Any, Protocol, TextIO, TypeAlias

from peon.agent import AgentMessage, ModelStreamChunk, ToolCall, TraceSink, Usage
from .coding_session import (
    CancellationEvent,
    CommandOutcomeEvent,
    MessageEvent,
    SelectionRequestEvent,
    StreamDeltaEvent,
    TerminalErrorEvent,
    TurnFinishedEvent,
    TurnStartedEvent,
)

logger = logging.getLogger(__name__)


class JsonlTraceSink:
    """Write metadata-only trace records as isolated JSON lines."""

    def __init__(self, output: TextIO | Path) -> None:
        self._output = output
        self._lock = Lock()

    def emit(self, record: Mapping[str, object]) -> None:
        line = json.dumps(dict(record), separators=(",", ":"))
        with self._lock:
            if isinstance(self._output, Path):
                with self._output.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            else:
                print(line, file=self._output)


def null_trace_sink() -> TraceSink | None:
    """Return the default disabled trace configuration."""
    return None


RedactionHook: TypeAlias = Callable[[Any], Any | Mapping[str, object] | None]


class EventJournalSink(Protocol):
    """Protocol for receiving and persisting runtime events for audit/replay."""

    def write_event(self, event: Any) -> None: ...


class JournalWriteError(RuntimeError):
    """Raised when strict event journaling fails."""

    pass


RuntimeEvent = (
    TurnStartedEvent
    | MessageEvent
    | StreamDeltaEvent
    | TurnFinishedEvent
    | CommandOutcomeEvent
    | SelectionRequestEvent
    | CancellationEvent
    | TerminalErrorEvent
)


def serialize_event(
    event: object,
    *,
    schema_version: int = 2,
    strict: bool = False,
) -> dict[str, object]:
    """Serialize one runtime event using the requested public schema."""
    if schema_version not in {1, 2}:
        raise ValueError("schema_version must be 1 or 2")
    if isinstance(event, Mapping):
        return _serialize_record(event, schema_version=schema_version, strict=strict)
    if not isinstance(event, _RUNTIME_EVENT_TYPES):
        if strict:
            raise TypeError(f"unsupported runtime event: {type(event).__name__}")
        return {
            "schema_version": schema_version,
            "event_type" if schema_version == 2 else "type": "diagnostic",
            "message": f"unsupported runtime event: {type(event).__name__}",
        }
    return _serialize_runtime_event(event, schema_version=schema_version)


def _serialize_record(
    record: Mapping[str, object],
    *,
    schema_version: int,
    strict: bool,
) -> dict[str, object]:
    """Serialize legacy host records through the same versioned boundary."""
    legacy_type = str(record.get("type", "diagnostic"))
    known_types = {
        "session_start",
        "session_end",
        "turn_start",
        "turn_end",
        "error",
        "user",
        "thinking",
        "tool_call",
        "tool_result",
        "assistant",
    }
    if legacy_type not in known_types:
        if strict:
            raise TypeError(f"unsupported runtime event: {legacy_type}")
        return {
            "schema_version": schema_version,
            "event_type" if schema_version == 2 else "type": "diagnostic",
            "message": f"unsupported runtime event: {legacy_type}",
        }
    if schema_version == 1:
        return {"type": legacy_type, "schema_version": 1, **{
            key: value for key, value in record.items() if key != "type"
        }}
    event_type = {
        "turn_start": "turn_started",
        "turn_end": "turn_finished",
        "error": "terminal_error",
        "user": "message",
        "assistant": "message",
        "tool_result": "message",
        "thinking": "stream_delta",
    }.get(legacy_type, legacy_type)
    result: dict[str, object] = {
        "schema_version": 2,
        "event_type": {
            "session_start": "session_started",
            "session_end": "session_finished",
        }.get(legacy_type, event_type),
    }
    allowed_fields = {
        "timestamp",
        "sequence",
        "session_id",
        "run_id",
        "turn_id",
        "content",
        "message",
        "role",
        "name",
        "arguments",
        "call_id",
        "duration",
        "usage",
        "status",
        "persistent",
    }
    for key, value in record.items():
        if key in allowed_fields and not (
            legacy_type == "session_start" and key == "persistent"
        ) and not (
            legacy_type == "session_end" and key == "success"
        ):
            result[key] = _serialize_value(value)
    if legacy_type in {"user", "assistant", "tool_result"}:
        result["role"] = {
            "user": "user",
            "assistant": "assistant",
            "tool_result": "tool",
        }[legacy_type]
    if legacy_type == "error" and "stop_reason" not in result:
        result["stop_reason"] = {
            "cancelled": "cancelled",
            "error": "provider_error",
        }.get(str(record.get("status", "error")), "provider_error")
    if legacy_type == "turn_end" and "stop_reason" not in result:
        result["stop_reason"] = (
            "completed"
            if record.get("status") == "success"
            else str(record.get("status", "provider_error"))
        )
    return result


_RUNTIME_EVENT_TYPES = (
    TurnStartedEvent,
    MessageEvent,
    StreamDeltaEvent,
    TurnFinishedEvent,
    CommandOutcomeEvent,
    SelectionRequestEvent,
    CancellationEvent,
    TerminalErrorEvent,
)


def _serialize_runtime_event(
    event: RuntimeEvent,
    *,
    schema_version: int,
) -> dict[str, object]:
    if schema_version == 1:
        return _serialize_schema_one(event)
    result: dict[str, object] = {
        "schema_version": 2,
        "event_type": event.event_type,
        "timestamp": event.timestamp.isoformat(),
        "sequence": event.sequence,
    }
    for event_field in fields(event):
        if event_field.name in {"schema_version", "timestamp", "sequence"}:
            continue
        result[event_field.name] = _serialize_value(getattr(event, event_field.name))
    if isinstance(event, TurnFinishedEvent):
        result["status"] = event.result.status
        result["stop_reason"] = event.result.stop_reason
    return result


def _serialize_schema_one(event: RuntimeEvent) -> dict[str, object]:
    if isinstance(event, TurnStartedEvent):
        return {
            "schema_version": 1,
            "type": "turn_start",
            "session_id": event.session_id,
            "run_id": event.run_id,
            "turn_id": event.turn_id,
            "started_at": event.started_at,
        }
    if isinstance(event, MessageEvent):
        message = event.message
        if message.role == "user":
            event_type = "user"
        elif message.role == "assistant" and message.tool_call is not None:
            event_type = "tool_call"
        elif message.role == "assistant":
            event_type = "assistant"
        elif message.role == "tool":
            event_type = "tool_result"
        else:
            event_type = message.role
        result: dict[str, object] = {
            "schema_version": 1,
            "type": event_type,
            "session_id": event.session_id,
            "run_id": event.run_id,
            "turn_id": event.turn_id,
        }
        if message.thinking:
            result["content"] = message.thinking
            result["type"] = "thinking"
        elif message.tool_call is not None:
            result.update(
                {
                    "name": message.tool_call.name,
                    "arguments": dict(message.tool_call.arguments),
                    "call_id": message.tool_call.call_id,
                }
            )
        else:
            result["content"] = message.content
            if message.tool_call_id is not None:
                result["call_id"] = message.tool_call_id
        return result
    if isinstance(event, TurnFinishedEvent):
        result = {
            "schema_version": 1,
            "type": "turn_end" if event.result.status == "success" else "error",
            "session_id": event.session_id,
            "run_id": event.run_id,
            "turn_id": event.turn_id,
            "duration": event.duration,
            "usage": _serialize_value(event.result.usage),
        }
        if event.result.status == "success":
            result.update({"success": True, "status": event.result.status})
        else:
            result.update(
                {
                    "message": event.result.error or "task failed",
                    "status": event.result.status,
                }
            )
        return result
    return {
        "schema_version": 1,
        "type": event.event_type,
        **{
            field.name: _serialize_value(getattr(event, field.name))
            for field in fields(event)
            if field.name not in {"schema_version", "timestamp", "sequence"}
        },
    }


def _serialize_value(val: object) -> object:
    if isinstance(val, AgentMessage):
        data: dict[str, object] = {"role": val.role, "content": val.content}
        thinking = val.thinking
        if thinking:
            data["thinking"] = thinking
        if val.tool_call is not None:
            data["tool_call"] = _serialize_value(val.tool_call)
        if val.tool_call_id is not None:
            data["tool_call_id"] = val.tool_call_id
            data["call_id"] = val.tool_call_id
        return data
    if isinstance(val, ModelStreamChunk):
        return {
            "delta": val.delta,
            "thinking_delta": val.thinking_delta,
            "tool_call_delta": _serialize_value(val.tool_call_delta),
            "finish_reason": val.finish_reason,
            "usage": _serialize_value(val.usage),
        }
    if isinstance(val, ToolCall):
        return {
            "name": val.name,
            "arguments": dict(val.arguments),
            "call_id": val.call_id,
        }
    if isinstance(val, Usage):
        return {
            "input_tokens": val.input_tokens,
            "output_tokens": val.output_tokens,
            "cache_tokens": val.cache_tokens,
            "cost": val.cost,
            "currency": val.currency,
        }
    if isinstance(val, datetime):
        return val.isoformat()
    if is_dataclass(val):
        return {
            field.name: _serialize_value(getattr(val, field.name))
            for field in fields(val)
        }
    if isinstance(val, Mapping):
        return {str(key): _serialize_value(value) for key, value in val.items()}
    if isinstance(val, (tuple, list)):
        return [_serialize_value(item) for item in val]
    return val


class FileEventJournalSink:
    """JSONL event journal sink with optional redaction hook and strict failure mode.

    NOTE: Prompts, assistant responses, tool arguments/output, paths, and secrets
    may appear in the journal. Use redaction_hook to filter or redact sensitive content.
    """

    def __init__(
        self,
        output: TextIO | Path,
        *,
        redaction_hook: RedactionHook | None = None,
        strict: bool = False,
    ) -> None:
        self._output = output
        self._redaction_hook = redaction_hook
        self.strict = strict
        self._lock = Lock()

    def write_event(self, event: Any) -> None:
        try:
            record: Any = event
            if self._redaction_hook is not None:
                record = self._redaction_hook(event)
                if record is None:
                    return

            encoded = serialize_event(record, strict=self.strict)

            line = json.dumps(encoded, separators=(",", ":"))
            with self._lock:
                if isinstance(self._output, Path):
                    with self._output.open("a", encoding="utf-8") as handle:
                        handle.write(line + "\n")
                else:
                    print(line, file=self._output)
                    self._output.flush()
        except Exception as error:
            if self.strict:
                raise JournalWriteError(f"Journal write failed: {error}") from error
            logger.warning("Event journal write failed: %s", error)


__all__ = [
    "EventJournalSink",
    "FileEventJournalSink",
    "JournalWriteError",
    "JsonlTraceSink",
    "RedactionHook",
    "null_trace_sink",
    "serialize_event",
]
