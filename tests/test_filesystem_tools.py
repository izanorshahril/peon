import re
import subprocess
import sys

from peon.agent import ToolExecutionContext
from peon.extensions import ExtensionRegistry
from peon.extensions.filesystem import register_filesystem_tools


def test_read_is_cwd_bound_and_supports_line_chunks(tmp_path) -> None:
    (tmp_path / "notes.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    registry = ExtensionRegistry()
    register_filesystem_tools(registry, root=tmp_path)

    assert registry.invoke("read", {"path": "notes.txt", "offset": 2, "limit": 1}) == (
        "two\n[truncated; continue with offset=3]"
    )
    traversal = registry.invoke("read", {"path": "../outside.txt"})
    assert traversal.startswith("read error:")
    assert "secret" not in traversal


def test_read_reports_bounded_continuation_and_invalid_utf8(tmp_path) -> None:
    (tmp_path / "large.txt").write_text("a\nb\nc\nd\n", encoding="utf-8")
    (tmp_path / "binary.txt").write_bytes(b"\xff\xfe")
    registry = ExtensionRegistry()
    register_filesystem_tools(registry, root=tmp_path, max_lines=2)

    assert registry.invoke("read", {"path": "large.txt"}) == (
        "a\nb\n[truncated; continue with offset=3]"
    )
    assert registry.invoke("read", {"path": "binary.txt"}).startswith(
        "read error:"
    )


def test_workspace_discovery_tools_are_bounded_and_skip_generated_directories(
    tmp_path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("needle here\n", encoding="utf-8")
    (tmp_path / "src" / "other.txt").write_text("nothing\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "ignored.py").write_text("needle\n", encoding="utf-8")
    (tmp_path / ".HG").mkdir()
    (tmp_path / ".HG" / "ignored-uppercase.py").write_text(
        "needle\n", encoding="utf-8"
    )
    (tmp_path / "NODE_MODULES").mkdir()
    (tmp_path / "NODE_MODULES" / "ignored.py").write_text(
        "needle\n", encoding="utf-8"
    )
    registry = ExtensionRegistry()
    register_filesystem_tools(registry, root=tmp_path, max_results=10)

    assert registry.invoke("ls", {"path": "."}) == "src/"
    assert registry.invoke("find", {"pattern": "*.py"}) == "src/main.py"
    assert registry.invoke("grep", {"pattern": "needle"}) == (
        "src/main.py:1:needle here"
    )


def test_workspace_discovery_tools_support_continuation_offsets(tmp_path) -> None:
    for name in ("a.py", "b.py", "c.py"):
        (tmp_path / name).write_text("needle\n", encoding="utf-8")
    registry = ExtensionRegistry()
    register_filesystem_tools(registry, root=tmp_path, max_results=1)

    assert registry.invoke("find", {"pattern": "*.py"}) == (
        "a.py\n[truncated; continue with offset=2]"
    )
    assert registry.invoke("find", {"pattern": "*.py", "offset": 2}) == (
        "b.py\n[truncated; continue with offset=3]"
    )
    assert registry.invoke("grep", {"pattern": "needle", "offset": 2}) == (
        "b.py:1:needle\n[truncated; continue with offset=3]"
    )


def test_read_long_line_continuation_uses_column(tmp_path) -> None:
    (tmp_path / "long.txt").write_text("abcdefghijk\nend\n", encoding="utf-8")
    registry = ExtensionRegistry()
    register_filesystem_tools(registry, root=tmp_path, max_output_chars=5)

    first = registry.invoke("read", {"path": "long.txt"})
    second = registry.invoke("read", {"path": "long.txt", "column": 6})

    assert first == "abcde\n[truncated; continue with offset=1&column=6]"
    assert second.startswith("fghij\n")


def test_read_continuation_keeps_later_selected_lines(tmp_path) -> None:
    (tmp_path / "mixed.txt").write_text("a\n123456789\nz\n", encoding="utf-8")
    registry = ExtensionRegistry()
    register_filesystem_tools(registry, root=tmp_path, max_output_chars=5)

    assert registry.invoke("read", {"path": "mixed.txt"}) == (
        "a\n123\n[truncated; continue with offset=2&column=4]"
    )


def test_workspace_tools_are_registered_with_expected_names(tmp_path) -> None:
    registry = ExtensionRegistry()
    register_filesystem_tools(registry, root=tmp_path)

    assert [tool.name for tool in registry.tools] == [
        "read",
        "write",
        "edit",
        "bash",
        "ls",
        "find",
        "grep",
    ]


def test_write_and_edit_are_cwd_bound_and_exact(tmp_path) -> None:
    registry = ExtensionRegistry()
    register_filesystem_tools(registry, root=tmp_path)

    write_result = registry.invoke(
        "write",
        {"path": "src/note.txt", "content": "one\ntwo\n"},
    )
    assert write_result == "write: wrote 8 bytes and 2 lines to src/note.txt"
    assert (tmp_path / "src" / "note.txt").read_text(encoding="utf-8") == (
        "one\ntwo\n"
    )
    assert registry.invoke(
        "edit",
        {"path": "src/note.txt", "old_text": "two", "new_text": "three"},
    ) == "edit: updated src/note.txt (line 2)"
    assert (tmp_path / "src" / "note.txt").read_text(encoding="utf-8") == (
        "one\nthree\n"
    )
    assert registry.invoke(
        "edit",
        {"path": "src/note.txt", "old_text": "missing", "new_text": "x"},
    ) == "edit error: old_text was not found"
    assert registry.invoke(
        "write",
        {"path": "../outside.txt", "content": "secret"},
    ).startswith("write error:")


def test_mutations_report_excluded_and_unicode_targets_without_writing(tmp_path) -> None:
    registry = ExtensionRegistry()
    register_filesystem_tools(registry, root=tmp_path)

    assert registry.invoke(
        "write",
        {"path": ".git/config", "content": "secret"},
    ) == "write error: '.git/config' is excluded"
    assert registry.invoke(
        "edit",
        {
            "path": "Credentials.JSON",
            "old_text": "secret",
            "new_text": "changed",
        },
    ) == "edit error: 'Credentials.JSON' is a sensitive target"
    assert registry.invoke(
        "write",
        {"path": "unicode.txt", "content": "café\n"},
    ) == "write: wrote 6 bytes and 1 lines to unicode.txt"


def test_edit_reports_ambiguous_unchanged_and_invalid_requests(tmp_path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("same\nsame\n", encoding="utf-8")
    registry = ExtensionRegistry()
    register_filesystem_tools(registry, root=tmp_path)

    assert registry.invoke(
        "edit",
        {"path": "notes.txt", "old_text": "same", "new_text": "changed"},
    ) == "edit error: old_text matched 2 times"
    target.write_text("same\nother\n", encoding="utf-8")
    assert registry.invoke(
        "edit",
        {"path": "notes.txt", "old_text": "same", "new_text": "same"},
    ) == "edit: no changes to notes.txt"
    assert registry.invoke(
        "edit",
        {"path": "notes.txt", "old_text": "", "new_text": "changed"},
    ) == "edit error: old_text must be a non-empty string"
    target.write_text("aaaa\n", encoding="utf-8")
    assert registry.invoke(
        "edit",
        {"path": "notes.txt", "old_text": "aaa", "new_text": "x"},
    ) == "edit error: old_text matched 2 times"


def test_mutations_reject_sensitive_targets_and_symlink_escapes(tmp_path) -> None:
    registry = ExtensionRegistry()
    register_filesystem_tools(registry, root=tmp_path)

    assert registry.invoke(
        "write",
        {"path": ".env", "content": "secret"},
    ) == "write error: '.env' is a sensitive target"
    assert registry.invoke(
        "write",
        {"path": ".ENV", "content": "secret"},
    ) == "write error: '.ENV' is a sensitive target"
    assert not (tmp_path / ".env").exists()

    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        return

    assert registry.invoke(
        "edit",
        {"path": "link.txt", "old_text": "secret", "new_text": "changed"},
    ) == "edit error: 'link.txt' is a symlink"
    assert registry.invoke(
        "write",
        {"path": "link.txt", "content": "changed"},
    ) == "write error: 'link.txt' is a symlink"
    assert outside.read_text(encoding="utf-8") == "secret"

    outside_directory = tmp_path.parent / "outside-directory"
    outside_directory.mkdir()
    nested_link = tmp_path / "nested-link"
    try:
        nested_link.symlink_to(outside_directory, target_is_directory=True)
    except (OSError, NotImplementedError):
        return

    assert registry.invoke(
        "write",
        {"path": "nested-link/child.txt", "content": "changed"},
    ) == "write error: 'nested-link/child.txt' is a symlink"
    assert not (outside_directory / "child.txt").exists()


def test_edit_preserves_crlf_newlines_and_reports_changed_lines(tmp_path) -> None:
    target = tmp_path / "notes.txt"
    target.write_bytes(b"one\r\ntwo\r\nthree\r\n")
    registry = ExtensionRegistry()
    register_filesystem_tools(registry, root=tmp_path)

    result = registry.invoke(
        "edit",
        {"path": "notes.txt", "old_text": "two", "new_text": "updated"},
    )

    assert result == "edit: updated notes.txt (line 2)"
    assert target.read_bytes() == b"one\r\nupdated\r\nthree\r\n"


def test_edit_preserves_mixed_newlines_and_normalizes_replacement_text(tmp_path) -> None:
    target = tmp_path / "mixed.txt"
    target.write_bytes(b"one\r\ntwo\nthree\r\nfour\n")
    registry = ExtensionRegistry()
    register_filesystem_tools(registry, root=tmp_path)

    result = registry.invoke(
        "edit",
        {"path": "mixed.txt", "old_text": "two\nthree", "new_text": "2\r\n3"},
    )

    assert result == "edit: updated mixed.txt (lines 2-3)"
    assert target.read_bytes() == b"one\r\n2\n3\r\nfour\n"


def test_edit_uses_local_newline_for_inserted_lines(tmp_path) -> None:
    target = tmp_path / "mixed.txt"
    target.write_bytes(b"one\r\ntwo\nthree\r\nfour\n")
    registry = ExtensionRegistry()
    register_filesystem_tools(registry, root=tmp_path)

    result = registry.invoke(
        "edit",
        {"path": "mixed.txt", "old_text": "two", "new_text": "2\r\nsecond"},
    )

    assert result == "edit: updated mixed.txt (lines 2-3)"
    assert target.read_bytes() == b"one\r\n2\nsecond\nthree\r\nfour\n"

    target.write_bytes(b"one\r\ntwo\nthree")
    result = registry.invoke(
        "edit",
        {"path": "mixed.txt", "old_text": "three", "new_text": "3\nfinal"},
    )

    assert result == "edit: updated mixed.txt (lines 3-4)"
    assert target.read_bytes() == b"one\r\ntwo\n3\nfinal"


def test_bash_runs_in_workspace_and_bounds_output(tmp_path) -> None:
    registry = ExtensionRegistry()
    register_filesystem_tools(registry, root=tmp_path, max_output_chars=20)

    result = registry.invoke("bash", {"command": "cd"})

    assert "bash: exit code 0" in result
    assert "stdout:" in result
    assert re.search(r"Took \d+\.\ds", result)

    truncated = registry.invoke("bash", {"command": "echo 1234567890123456789012345"})
    assert "\n[truncated]\n" in truncated
    assert re.search(r"Took \d+\.\ds$", truncated)


def test_bash_streams_output_and_reports_cancellation(tmp_path) -> None:
    streamed: list[tuple[str, str]] = []
    context = ToolExecutionContext(
        on_output=lambda stream, chunk: (
            streamed.append((stream, chunk)),
            context.cancel(),
        )[-1]
    )
    command = subprocess.list2cmdline(
        [
            sys.executable,
            "-c",
            "import sys,time; print('before-cancel', flush=True); time.sleep(10)",
        ]
    )
    registry = ExtensionRegistry()
    register_filesystem_tools(registry, root=tmp_path)

    result = registry.invoke_with_context(
        "bash",
        {"command": command, "timeout": 30},
        context,
    )

    assert "bash: cancelled" in result
    assert "status: cancelled" in result
    assert "before-cancel" in result
    assert streamed
    assert streamed[0][0] == "stdout"


def test_bash_reports_stderr_and_nonzero_exit_status(tmp_path) -> None:
    command = subprocess.list2cmdline(
        [
            sys.executable,
            "-c",
            "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)",
        ]
    )
    registry = ExtensionRegistry()
    register_filesystem_tools(registry, root=tmp_path)

    result = registry.invoke("bash", {"command": command})

    assert "bash: exit code 3" in result
    assert "status: exited" in result
    assert "stdout:\nout" in result
    assert "stderr:\nerr" in result


def test_bash_reports_timeout_without_requiring_bash(tmp_path) -> None:
    command = subprocess.list2cmdline(
        [sys.executable, "-c", "import time; time.sleep(10)"]
    )
    registry = ExtensionRegistry()
    register_filesystem_tools(registry, root=tmp_path)

    result = registry.invoke("bash", {"command": command, "timeout": 0.2})

    assert "bash: timed out after 0.2 seconds" in result
    assert "status: timed out" in result


def test_bash_marks_truncated_output_and_keeps_workspace_cwd(tmp_path) -> None:
    command = subprocess.list2cmdline(
        [
            sys.executable,
            "-c",
            "import os; print(os.getcwd()); print('x' * 200)",
        ]
    )
    registry = ExtensionRegistry()
    register_filesystem_tools(
        registry,
        root=tmp_path,
        max_output_chars=len(str(tmp_path)) + 20,
    )

    result = registry.invoke("bash", {"command": command})

    assert str(tmp_path) in result
    assert "[truncated]" in result
    assert "status: exited" in result


def test_discovery_continuation_keeps_result_offset_after_character_limit(tmp_path) -> None:
    (tmp_path / "a.py").write_text("", encoding="utf-8")
    (tmp_path / "long_name.py").write_text("", encoding="utf-8")
    (tmp_path / "z.py").write_text("", encoding="utf-8")
    registry = ExtensionRegistry()
    register_filesystem_tools(registry, root=tmp_path, max_output_chars=10)

    assert registry.invoke("find", {"pattern": "*.py"}) == (
        "a.py\nlong_\n[truncated; continue with offset=2&column=6]"
    )


def test_include_hidden_does_not_reenable_generated_directories(tmp_path) -> None:
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "hidden.py").write_text("needle\n", encoding="utf-8")
    (tmp_path / ".config").mkdir()
    (tmp_path / ".config" / "visible.py").write_text("needle\n", encoding="utf-8")
    registry = ExtensionRegistry()
    register_filesystem_tools(registry, root=tmp_path)

    assert registry.invoke("find", {"pattern": "*.py", "include_hidden": True}) == (
        ".config/visible.py"
    )
    assert registry.invoke("grep", {"pattern": "needle", "include_hidden": True}) == (
        ".config/visible.py:1:needle"
    )


def test_discovery_rejects_explicit_generated_directory_roots(tmp_path) -> None:
    generated = tmp_path / "node_modules"
    generated.mkdir()
    (generated / "hidden.py").write_text("needle\n", encoding="utf-8")
    registry = ExtensionRegistry()
    register_filesystem_tools(registry, root=tmp_path)

    assert registry.invoke("ls", {"path": "node_modules"}).startswith("ls error:")
    assert registry.invoke("find", {"path": "node_modules"}).startswith("find error:")
    assert registry.invoke("grep", {"path": "node_modules", "pattern": "needle"}).startswith(
        "grep error:"
    )


def test_grep_skips_invalid_utf8_files(tmp_path) -> None:
    (tmp_path / "binary.dat").write_bytes(b"needle\xff\n")
    (tmp_path / "valid.txt").write_text("needle\n", encoding="utf-8")
    registry = ExtensionRegistry()
    register_filesystem_tools(registry, root=tmp_path)

    assert registry.invoke("grep", {"pattern": "needle"}) == "valid.txt:1:needle"
