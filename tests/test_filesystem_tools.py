import re

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

    assert registry.invoke(
        "write",
        {"path": "src/note.txt", "content": "one\ntwo\n"},
    ).startswith("write: wrote")
    assert (tmp_path / "src" / "note.txt").read_text(encoding="utf-8") == (
        "one\ntwo\n"
    )
    assert registry.invoke(
        "edit",
        {"path": "src/note.txt", "old_text": "two", "new_text": "three"},
    ) == "edit: updated src/note.txt"
    assert (tmp_path / "src" / "note.txt").read_text(encoding="utf-8") == (
        "one\nthree\n"
    )
    assert registry.invoke(
        "edit",
        {"path": "src/note.txt", "old_text": "missing", "new_text": "x"},
    ).startswith("edit error:")
    assert registry.invoke(
        "write",
        {"path": "../outside.txt", "content": "secret"},
    ).startswith("write error:")


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