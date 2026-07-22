"""Application-owned performance trace sinks and event journaling."""

from collections.abc import Callable, Mapping
import json
import logging
from pathlib import Path
import re
from threading import Lock
from typing import Any, Protocol, TextIO, TypeAlias

from peon.agent import AgentMessage, ModelStreamChunk, TraceSink

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


def serialize_event(event: object) -> dict[str, object]:
    """Serialize a SessionEvent to a schema version 2 event dictionary."""
    if hasattr(event, "__dataclass_fields__"):
        result: dict[str, object] = {"schema_version": 2}
        event_name = type(event).__name__
        if event_name.endswith("Event"):
            event_name = event_name[:-5]
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", event_name)
        result["event_type"] = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

        for field_name in getattr(event, "__dataclass_fields__"):
            val = getattr(event, field_name)
            result[field_name] = _serialize_value(val)
        return result
    return {"schema_version": 2, "raw": str(event)}


def _serialize_value(val: object) -> object:
    if isinstance(val, AgentMessage):
        data: dict[str, object] = {"role": val.role, "content": val.content}
        thinking = getattr(val, "thinking", None)
        if thinking:
            data["thinking"] = thinking
        call_id = getattr(val, "call_id", None)
        if call_id:
            data["call_id"] = call_id
        tool_calls = getattr(val, "tool_calls", None)
        if tool_calls:
            data["tool_calls"] = [
                {
                    "name": tc.name,
                    "arguments": tc.arguments,
                    "call_id": getattr(tc, "call_id", None),
                }
                for tc in tool_calls
            ]
        return data
    if isinstance(val, ModelStreamChunk):
        return {
            "delta": val.delta,
            "thinking_delta": val.thinking_delta,
            "finish_reason": val.finish_reason,
        }
    if hasattr(val, "to_dict") and callable(getattr(val, "to_dict")):
        return val.to_dict()
    if hasattr(val, "__dataclass_fields__"):
        return serialize_event(val)
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

            if hasattr(record, "__dataclass_fields__"):
                encoded = serialize_event(record)
            elif isinstance(record, Mapping):
                encoded = dict(record)
            else:
                encoded = {"schema_version": 2, "raw": str(record)}

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
