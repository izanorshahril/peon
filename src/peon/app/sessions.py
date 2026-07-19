"""Append-only conversation sessions owned by the application layer."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import inspect
import json
import os
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from peon.agent import AgentMessage, ToolCall


class SessionStoreError(Exception):
    """Raised when a persisted session cannot be decoded safely."""


@dataclass(frozen=True, slots=True)
class SessionRecord:
    session_id: str
    messages: tuple[AgentMessage, ...] = ()
    cwd: str | None = None
    created_at: str | None = None
    parent_id: str | None = None
    name: str | None = None


class SessionStore(Protocol):
    def create(
        self,
        *,
        parent_id: str | None = None,
        name: str | None = None,
    ) -> SessionRecord:
        """Create and select a fresh conversation session."""

    def append(self, session_id: str, message: AgentMessage) -> None:
        """Append one provider-neutral message to a session."""

    def load(self, session_id: str) -> SessionRecord:
        """Load one session by ID."""

    def load_latest(self) -> SessionRecord | None:
        """Load the most recently modified session, if one exists."""

    def list_sessions(self) -> tuple[SessionRecord, ...]:
        """List valid sessions for the current working directory."""

    def load_current(self, session_id: str) -> SessionRecord:
        """Load one session after checking its working directory."""

    def load_path(self, path: Path) -> SessionRecord:
        """Load one explicitly selected session file."""


def select_session(store: SessionStore, target: str) -> SessionRecord:
    """Resolve an exact session path, current-directory ID, or unique name."""
    normalized_target = target.strip()
    if not normalized_target:
        raise SessionStoreError("session target cannot be blank")
    target_path = Path(normalized_target).expanduser()
    if target_path.suffix == ".jsonl" or target_path.parent != Path("."):
        load_path = getattr(store, "load_path", None)
        if load_path is not None:
            return load_path(target_path)
    try:
        return store.load_current(normalized_target)
    except SessionStoreError as direct_error:
        try:
            sessions = store.list_sessions()
        except AttributeError:
            raise direct_error
        matches = tuple(
            session
            for session in sessions
            if session.name == normalized_target
        )
        if not matches:
            raise direct_error
        if len(matches) > 1:
            raise SessionStoreError(
                f"session name '{normalized_target}' is ambiguous"
            )
        return store.load_current(matches[0].session_id)


def create_session(
    store: SessionStore,
    *,
    parent_id: str | None = None,
    name: str | None = None,
) -> SessionRecord:
    """Create a session while accepting stores from the v1 API."""
    if parent_id is None and name is None:
        return store.create()
    try:
        parameters = inspect.signature(store.create).parameters
    except (TypeError, ValueError):
        return store.create()
    accepts_kwargs = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    keyword_arguments = {}
    if parent_id is not None and (accepts_kwargs or "parent_id" in parameters):
        keyword_arguments["parent_id"] = parent_id
    if name is not None and (accepts_kwargs or "name" in parameters):
        keyword_arguments["name"] = name
    return store.create(**keyword_arguments)


class JsonlSessionStore:
    """Store each conversation as a separate append-only JSONL file."""

    def __init__(
        self,
        directory: Path | None = None,
        *,
        working_directory: Path | None = None,
    ) -> None:
        self.directory = directory or default_session_directory()
        self.working_directory = str(
            (working_directory or Path.cwd()).resolve()
        )

    def create(
        self,
        *,
        parent_id: str | None = None,
        name: str | None = None,
    ) -> SessionRecord:
        self.directory.mkdir(parents=True, exist_ok=True)
        session_id = uuid4().hex
        created_at = _utc_timestamp()
        path = self._path_for(session_id)
        header = {
            "type": "session",
            "version": 2,
            "session_id": session_id,
            "cwd": self.working_directory,
            "created_at": created_at,
            "parent_id": parent_id,
            "name": name,
        }
        path.write_text(json.dumps(header, separators=(",", ":")) + "\n", encoding="utf-8")
        return SessionRecord(
            session_id=session_id,
            cwd=self.working_directory,
            created_at=created_at,
            parent_id=parent_id,
            name=name,
        )

    def append(self, session_id: str, message: AgentMessage) -> None:
        path = self._path_for(session_id)
        if not path.is_file():
            raise SessionStoreError(f"session '{session_id}' does not exist")
        _repair_trailing_record(path)
        record = {
            "type": "message",
            "message": _serialize_message(message),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")

    def load(self, session_id: str) -> SessionRecord:
        path = self._path_for(session_id)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise SessionStoreError(f"could not read session '{path.name}'") from error
        return _decode_session(path, text)

    def load_latest(self) -> SessionRecord | None:
        try:
            paths = sorted(
                self.directory.glob("*.jsonl"),
                key=lambda path: (path.stat().st_mtime_ns, path.name),
                reverse=True,
            )
        except OSError as error:
            raise SessionStoreError("could not inspect session storage") from error
        if not paths:
            return None
        first_error: SessionStoreError | None = None
        for path in paths:
            try:
                text = path.read_text(encoding="utf-8")
                try:
                    header = json.loads(text.splitlines()[0])
                except (IndexError, json.JSONDecodeError):
                    header = None
                if (
                    isinstance(header, Mapping)
                    and header.get("type") == "session"
                    and header.get("version") == 2
                    and isinstance(header.get("cwd"), str)
                    and header["cwd"] != self.working_directory
                ):
                    continue
                record = _decode_session(path, text)
                if record.cwd != self.working_directory:
                    continue
                return record
            except SessionStoreError as error:
                first_error = first_error or error
            except (OSError, UnicodeDecodeError) as error:
                first_error = first_error or SessionStoreError(
                    f"could not read session '{path.name}'"
                )
        if first_error is not None:
            raise first_error
        return None

    def list_sessions(self) -> tuple[SessionRecord, ...]:
        try:
            paths = sorted(
                self.directory.glob("*.jsonl"),
                key=lambda path: (path.stat().st_mtime_ns, path.name),
                reverse=True,
            )
        except OSError as error:
            raise SessionStoreError("could not inspect session storage") from error
        sessions: list[SessionRecord] = []
        for path in paths:
            try:
                record = _decode_session(path, path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, SessionStoreError):
                continue
            if record.cwd == self.working_directory:
                sessions.append(record)
        return tuple(sessions)

    def load_current(self, session_id: str) -> SessionRecord:
        record = self.load(session_id)
        if record.cwd is not None and record.cwd != self.working_directory:
            raise SessionStoreError(
                f"session '{session_id}' belongs to another working directory"
            )
        return record

    def load_path(self, path: Path) -> SessionRecord:
        try:
            resolved_path = path.resolve()
            text = resolved_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise SessionStoreError(
                f"could not open session file '{path}'"
            ) from error
        return _decode_session(resolved_path, text)

    def _path_for(self, session_id: str) -> Path:
        if not session_id or Path(session_id).name != session_id:
            raise SessionStoreError("invalid session ID")
        return self.directory / f"{session_id}.jsonl"


@dataclass(slots=True)
class MemorySessionStore:
    """Small in-memory store for embedded use and application tests."""

    records: dict[str, list[AgentMessage]] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    metadata: dict[str, SessionRecord] = field(default_factory=dict)
    working_directory: str = field(
        default_factory=lambda: str(Path.cwd().resolve())
    )

    def create(
        self,
        *,
        parent_id: str | None = None,
        name: str | None = None,
    ) -> SessionRecord:
        session_id = uuid4().hex
        self.records[session_id] = []
        self.order.append(session_id)
        session = SessionRecord(
            session_id=session_id,
            cwd=self.working_directory,
            created_at=_utc_timestamp(),
            parent_id=parent_id,
            name=name,
        )
        self.metadata[session_id] = session
        return session

    def append(self, session_id: str, message: AgentMessage) -> None:
        try:
            self.records[session_id].append(message)
        except KeyError as error:
            raise SessionStoreError(f"session '{session_id}' does not exist") from error

    def load(self, session_id: str) -> SessionRecord:
        try:
            messages = self.records[session_id]
        except KeyError as error:
            raise SessionStoreError(f"session '{session_id}' does not exist") from error
        metadata = self.metadata.get(session_id)
        return SessionRecord(
            session_id=session_id,
            messages=tuple(messages),
            cwd=metadata.cwd if metadata is not None else self.working_directory,
            created_at=metadata.created_at if metadata is not None else None,
            parent_id=metadata.parent_id if metadata is not None else None,
            name=metadata.name if metadata is not None else None,
        )

    def load_latest(self) -> SessionRecord | None:
        if not self.order:
            return None
        return self.load(self.order[-1])

    def list_sessions(self) -> tuple[SessionRecord, ...]:
        return tuple(
            self.load(session_id)
            for session_id in reversed(self.order)
        )

    def load_current(self, session_id: str) -> SessionRecord:
        return self.load(session_id)

    def load_path(self, path: Path) -> SessionRecord:
        raise SessionStoreError(
            f"session file paths are unavailable for in-memory sessions: '{path}'"
        )


def default_session_directory() -> Path:
    configured = os.environ.get("PEON_SESSION_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".peon" / "sessions"


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize_message(message: AgentMessage) -> dict[str, object]:
    raw: dict[str, object] = {
        "role": message.role,
        "content": message.content,
    }
    if message.thinking is not None:
        raw["thinking"] = message.thinking
    if message.tool_call is not None:
        raw["tool_call"] = {
            "name": message.tool_call.name,
            "arguments": dict(message.tool_call.arguments),
            "call_id": message.tool_call.call_id,
        }
    if message.tool_call_id is not None:
        raw["tool_call_id"] = message.tool_call_id
    return raw


def _repair_trailing_record(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise SessionStoreError(f"could not read session '{path.name}'") from error
    lines = text.splitlines(keepends=True)
    if not lines:
        raise SessionStoreError(f"session '{path.name}' is incomplete")
    tail_start = sum(len(line) for line in lines[:-1])
    tail = lines[-1].rstrip("\r\n")
    try:
        record = json.loads(tail)
    except json.JSONDecodeError:
        if tail_start == 0:
            raise SessionStoreError(f"session '{path.name}' has an invalid header")
        repaired = text[:tail_start]
    else:
        if not isinstance(record, Mapping) or record.get("type") not in {
            "session",
            "message",
        }:
            raise SessionStoreError(f"session '{path.name}' has an invalid record")
        if text.endswith(("\n", "\r")):
            return
        repaired = text + "\n"
    try:
        path.write_text(repaired, encoding="utf-8")
    except OSError as error:
        raise SessionStoreError(f"could not repair session '{path.name}'") from error


def _decode_session(path: Path, text: str) -> SessionRecord:
    lines = text.splitlines()
    if not lines:
        raise SessionStoreError(f"session '{path.name}' is incomplete")
    try:
        header = json.loads(lines[0])
    except json.JSONDecodeError as error:
        raise SessionStoreError(f"session '{path.name}' is corrupt") from error
    if not isinstance(header, Mapping):
        raise SessionStoreError(f"session '{path.name}' has an invalid header")
    if header.get("type") != "session" or header.get("version") not in {1, 2}:
        raise SessionStoreError(f"session '{path.name}' has an invalid header")
    session_id = header.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise SessionStoreError(f"session '{path.name}' has an invalid ID")
    if session_id != path.stem:
        raise SessionStoreError(f"session '{path.name}' has a mismatched ID")
    cwd = header.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        raise SessionStoreError(f"session '{path.name}' has an invalid cwd")
    created_at = header.get("created_at")
    if created_at is not None and not isinstance(created_at, str):
        raise SessionStoreError(f"session '{path.name}' has an invalid timestamp")
    parent_id = header.get("parent_id")
    if parent_id is not None and not isinstance(parent_id, str):
        raise SessionStoreError(f"session '{path.name}' has an invalid parent ID")
    name = header.get("name")
    if name is not None and not isinstance(name, str):
        raise SessionStoreError(f"session '{path.name}' has an invalid name")

    messages: list[AgentMessage] = []
    for line_number, line in enumerate(lines[1:], start=2):
        try:
            raw_record = json.loads(line)
        except json.JSONDecodeError as error:
            if line_number == len(lines) and not text.endswith(("\n", "\r")):
                break
            raise SessionStoreError(
                f"session '{path.name}' is corrupt at line {line_number}"
            ) from error
        if not isinstance(raw_record, Mapping) or raw_record.get("type") != "message":
            raise SessionStoreError(
                f"session '{path.name}' has an invalid record at line {line_number}"
            )
        try:
            messages.append(_deserialize_message(raw_record.get("message")))
        except (TypeError, ValueError, KeyError) as error:
            raise SessionStoreError(
                f"session '{path.name}' has an invalid message at line {line_number}"
            ) from error
    return SessionRecord(
        session_id=session_id,
        messages=tuple(messages),
        cwd=cwd,
        created_at=created_at,
        parent_id=parent_id,
        name=name,
    )


def _deserialize_message(raw: object) -> AgentMessage:
    if not isinstance(raw, Mapping):
        raise TypeError("message must be an object")
    role = raw.get("role")
    if role not in {"system", "developer", "user", "assistant", "tool"}:
        raise ValueError("invalid message role")
    content = raw.get("content")
    if not isinstance(content, str):
        raise ValueError("invalid message content")
    thinking = raw.get("thinking")
    if thinking is not None and not isinstance(thinking, str):
        raise ValueError("invalid thinking content")
    tool_call = _deserialize_tool_call(raw.get("tool_call"))
    tool_call_id = raw.get("tool_call_id")
    if tool_call_id is not None and not isinstance(tool_call_id, str):
        raise ValueError("invalid tool call ID")
    return AgentMessage(
        role=role,
        content=content,
        thinking=thinking,
        tool_call=tool_call,
        tool_call_id=tool_call_id,
    )


def _deserialize_tool_call(raw: object) -> ToolCall | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise TypeError("tool call must be an object")
    name = raw.get("name")
    arguments = raw.get("arguments")
    call_id = raw.get("call_id")
    if not isinstance(name, str) or not name:
        raise ValueError("invalid tool name")
    if not isinstance(arguments, Mapping):
        raise ValueError("invalid tool arguments")
    if call_id is not None and not isinstance(call_id, str):
        raise ValueError("invalid tool call ID")
    return ToolCall(name=name, arguments=dict(arguments), call_id=call_id)