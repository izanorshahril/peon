import json
import os

import pytest

from peon.agent import AgentMessage, ToolCall
from peon.app.sessions import JsonlSessionStore, SessionStoreError


def test_jsonl_session_store_round_trips_tool_messages(tmp_path) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    session = store.create()
    messages = (
        AgentMessage(role="user", content="Count the words."),
        AgentMessage(
            role="assistant",
            content="",
            tool_call=ToolCall(
                name="word_count",
                arguments={"text": "one two"},
                call_id="call-1",
            ),
        ),
        AgentMessage(role="tool", content="word count: 2", tool_call_id="call-1"),
        AgentMessage(role="assistant", content="There are two words."),
    )

    for message in messages:
        store.append(session.session_id, message)

    assert store.load(session.session_id) == session.__class__(
        session_id=session.session_id,
        messages=messages,
        cwd=session.cwd,
        created_at=session.created_at,
        parent_id=session.parent_id,
    )
    assert store.load_latest() == session.__class__(
        session_id=session.session_id,
        messages=messages,
        cwd=session.cwd,
        created_at=session.created_at,
        parent_id=session.parent_id,
    )


def test_jsonl_session_store_writes_metadata_and_reads_legacy_sessions(tmp_path) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    current = store.create()
    header = json.loads(
        (tmp_path / "sessions" / f"{current.session_id}.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )

    assert header["version"] == 2
    assert header["session_id"] == current.session_id
    assert isinstance(header["cwd"], str)
    assert isinstance(header["created_at"], str)

    legacy_id = "legacy-session"
    (tmp_path / "sessions" / f"{legacy_id}.jsonl").write_text(
        json.dumps(
            {"type": "session", "version": 1, "session_id": legacy_id}
        )
        + "\n"
        + json.dumps(
            {
                "type": "message",
                "message": {"role": "user", "content": "legacy task"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    loaded = store.load(legacy_id)

    assert loaded.session_id == legacy_id
    assert loaded.messages == (AgentMessage(role="user", content="legacy task"),)


def test_jsonl_session_store_does_not_continue_legacy_session_without_cwd(
    tmp_path,
) -> None:
    directory = tmp_path / "sessions"
    directory.mkdir()
    legacy_id = "legacy-session"
    (directory / f"{legacy_id}.jsonl").write_text(
        json.dumps(
            {"type": "session", "version": 1, "session_id": legacy_id}
        )
        + "\n",
        encoding="utf-8",
    )

    store = JsonlSessionStore(directory, working_directory=tmp_path / "project")

    assert store.load_latest() is None
    assert store.load(legacy_id).session_id == legacy_id


def test_jsonl_store_ignores_corrupt_session_from_another_directory(tmp_path) -> None:
    directory = tmp_path / "sessions"
    store = JsonlSessionStore(directory, working_directory=tmp_path / "project")
    valid = store.create()
    store.append(valid.session_id, AgentMessage(role="user", content="kept"))
    os.utime(
        directory / f"{valid.session_id}.jsonl",
        ns=(1_000_000_000, 1_000_000_000),
    )
    foreign = directory / "foreign.jsonl"
    foreign.write_text(
        json.dumps(
            {
                "type": "session",
                "version": 2,
                "session_id": "foreign",
                "cwd": str((tmp_path / "other").resolve()),
                "created_at": "2025-01-01T00:00:00+00:00",
                "parent_id": None,
            }
        )
        + "\n{not-json}\n",
        encoding="utf-8",
    )
    os.utime(foreign, ns=(2_000_000_000, 2_000_000_000))

    loaded = store.load_latest()

    assert loaded is not None
    assert loaded.session_id == valid.session_id


def test_jsonl_session_store_creates_new_session_without_rewriting_previous(tmp_path) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    first = store.create()
    store.append(first.session_id, AgentMessage(role="user", content="old"))
    first_file = next((tmp_path / "sessions").glob("*.jsonl"))
    first_contents = first_file.read_text(encoding="utf-8")

    second = store.create()
    store.append(second.session_id, AgentMessage(role="user", content="new"))

    assert first_file.read_text(encoding="utf-8") == first_contents
    latest = store.load_latest()
    assert latest is not None
    assert latest.session_id == second.session_id


def test_jsonl_session_store_reports_corrupt_data(tmp_path) -> None:
    directory = tmp_path / "sessions"
    directory.mkdir()
    path = directory / "broken.jsonl"
    path.write_text(
        json.dumps({"type": "session", "version": 1, "session_id": "broken"})
        + "\n{not-json}\n",
        encoding="utf-8",
    )
    store = JsonlSessionStore(directory)

    with pytest.raises(SessionStoreError, match="broken.jsonl"):
        store.load_latest()


def test_jsonl_session_store_falls_back_to_latest_valid_session(tmp_path) -> None:
    directory = tmp_path / "sessions"
    store = JsonlSessionStore(directory)
    valid = store.create()
    store.append(valid.session_id, AgentMessage(role="user", content="kept"))
    os.utime(directory / f"{valid.session_id}.jsonl", ns=(1_000_000_000, 1_000_000_000))
    corrupt = directory / "newest.jsonl"
    corrupt.write_text(
        json.dumps({"type": "session", "version": 1, "session_id": "newest"})
        + "\n{not-json}\n",
        encoding="utf-8",
    )
    os.utime(corrupt, ns=(2_000_000_000, 2_000_000_000))

    loaded = store.load_latest()

    assert loaded is not None
    assert loaded.session_id == valid.session_id


def test_jsonl_session_store_ignores_only_an_incomplete_trailing_record(tmp_path) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    session = store.create()
    store.append(session.session_id, AgentMessage(role="user", content="kept"))
    path = tmp_path / "sessions" / f"{session.session_id}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"type":"message"')

    loaded = store.load(session.session_id)

    assert loaded.messages == (AgentMessage(role="user", content="kept"),)

    store.append(session.session_id, AgentMessage(role="user", content="continued"))

    assert store.load(session.session_id).messages == (
        AgentMessage(role="user", content="kept"),
        AgentMessage(role="user", content="continued"),
    )


def test_jsonl_session_store_repairs_incomplete_trailing_record_with_newline(tmp_path) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    session = store.create()
    store.append(session.session_id, AgentMessage(role="user", content="kept"))
    path = tmp_path / "sessions" / f"{session.session_id}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"type":"message"\n')

    store.append(session.session_id, AgentMessage(role="user", content="continued"))

    assert store.load(session.session_id).messages == (
        AgentMessage(role="user", content="kept"),
        AgentMessage(role="user", content="continued"),
    )