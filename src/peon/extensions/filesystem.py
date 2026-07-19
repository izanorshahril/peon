"""Cwd-bound filesystem and shell tools for the application registry."""

from collections.abc import Iterator, Mapping
from fnmatch import fnmatch
import os
from pathlib import Path
import re
import subprocess
import time

from .registry import ExtensionRegistry

_DEFAULT_EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "build",
        "dist",
        "node_modules",
        "__pycache__",
        "venv",
    }
)
_SENSITIVE_FILE_NAMES = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        ".env.development",
        "credentials.json",
        "secrets.json",
        "id_rsa",
        "id_ed25519",
    }
)


def register_filesystem_tools(
    registry: ExtensionRegistry,
    *,
    root: Path | None = None,
    max_lines: int = 200,
    max_results: int = 100,
    max_output_chars: int = 12000,
) -> None:
    """Register cwd-bound filesystem and shell tools."""
    workspace = (root or Path.cwd()).resolve()
    if max_lines < 1 or max_results < 1 or max_output_chars < 1:
        raise ValueError("filesystem output limits must be positive")

    registry.register_tool(
        name="read",
        description="Read a UTF-8 text file by bounded line ranges.",
        parameters={
            "type": "object",
            "required": ["path"],
            "properties": {
                "path": {"type": "string"},
                "offset": {"type": "integer", "minimum": 1},
                "limit": {"type": "integer", "minimum": 1},
                "column": {"type": "integer", "minimum": 1},
            },
        },
        handler=lambda arguments: _read(
            workspace,
            arguments,
            max_lines=max_lines,
            max_output_chars=max_output_chars,
        ),
    )
    registry.register_tool(
        name="write",
        description="Create or replace a UTF-8 text file within the workspace.",
        parameters={
            "type": "object",
            "required": ["path", "content"],
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
        },
        handler=lambda arguments: _write(workspace, arguments),
    )
    registry.register_tool(
        name="edit",
        description="Replace one exact text match in a workspace file.",
        parameters={
            "type": "object",
            "required": ["path", "old_text", "new_text"],
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
            },
        },
        handler=lambda arguments: _edit(workspace, arguments),
    )
    registry.register_tool(
        name="bash",
        description="Run a command in the workspace with bounded output.",
        parameters={
            "type": "object",
            "required": ["command"],
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "number", "minimum": 1},
            },
        },
        handler=lambda arguments: _bash(
            workspace,
            arguments,
            max_output_chars=max_output_chars,
        ),
    )
    registry.register_tool(
        name="ls",
        description="List entries in a cwd-bound directory.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "include_hidden": {"type": "boolean"},
                "offset": {"type": "integer", "minimum": 1},
                "column": {"type": "integer", "minimum": 1},
            },
        },
        handler=lambda arguments: _ls(
            workspace,
            arguments,
            max_results=max_results,
            max_output_chars=max_output_chars,
        ),
    )
    registry.register_tool(
        name="find",
        description="Find files by name within the cwd-bound workspace.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "pattern": {"type": "string"},
                "include_hidden": {"type": "boolean"},
                "offset": {"type": "integer", "minimum": 1},
                "column": {"type": "integer", "minimum": 1},
            },
        },
        handler=lambda arguments: _find(
            workspace,
            arguments,
            max_results=max_results,
            max_output_chars=max_output_chars,
        ),
    )
    registry.register_tool(
        name="grep",
        description="Search UTF-8 text files within the cwd-bound workspace.",
        parameters={
            "type": "object",
            "required": ["pattern"],
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string"},
                "case_sensitive": {"type": "boolean"},
                "include_hidden": {"type": "boolean"},
                "offset": {"type": "integer", "minimum": 1},
                "column": {"type": "integer", "minimum": 1},
            },
        },
        handler=lambda arguments: _grep(
            workspace,
            arguments,
            max_results=max_results,
            max_output_chars=max_output_chars,
        ),
    )


def _write(root: Path, arguments: Mapping[str, object]) -> str:
    path, error = _resolve_mutation_path(root, arguments, operation="write")
    if error is not None:
        return error
    content = arguments.get("content")
    if not isinstance(content, str):
        return "write error: content must be a string"
    assert path is not None
    policy_error = _mutation_policy_error(root, path, operation="write")
    if policy_error is not None:
        return policy_error
    if path.exists() and path.is_dir():
        return f"write error: '{_display_path(root, path)}' is a directory"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        policy_error = _mutation_policy_error(root, path, operation="write")
        if policy_error is not None:
            return policy_error
        path.write_bytes(content.encode("utf-8"))
    except OSError as error:
        return f"write error: could not write '{_display_path(root, path)}': {error}"
    normalized_content = _normalize_newlines(content)
    line_count = normalized_content.count("\n") + (
        1 if normalized_content and not normalized_content.endswith("\n") else 0
    )
    byte_count = len(content.encode("utf-8"))
    return f"write: wrote {byte_count} bytes and {line_count} lines to {_display_path(root, path)}"


def _edit(root: Path, arguments: Mapping[str, object]) -> str:
    path, error = _resolve_mutation_path(root, arguments, operation="edit")
    if error is not None:
        return error
    old_text = arguments.get("old_text")
    new_text = arguments.get("new_text")
    if not isinstance(old_text, str) or not isinstance(new_text, str):
        return "edit error: old_text and new_text must be strings"
    assert path is not None
    policy_error = _mutation_policy_error(root, path, operation="edit")
    if policy_error is not None:
        return policy_error
    if not path.is_file():
        return f"edit error: '{_display_path(root, path)}' is not a file"
    try:
        raw_content = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return f"edit error: could not read '{_display_path(root, path)}': {error}"
    content, offsets = _normalize_with_offsets(raw_content)
    normalized_old_text = _normalize_newlines(old_text)
    normalized_new_text = _normalize_newlines(new_text)
    if not old_text:
        return "edit error: old_text must be a non-empty string"
    matches = _count_overlapping(content, normalized_old_text)
    if matches == 0:
        return "edit error: old_text was not found"
    if matches > 1:
        return f"edit error: old_text matched {matches} times"
    start = content.index(normalized_old_text)
    end = start + len(normalized_old_text)
    raw_start = offsets[start]
    raw_end = offsets[end]
    replacement = _replacement_text(
        normalized_new_text,
        raw_content[raw_start:raw_end],
        raw_content,
        raw_start,
        raw_end,
    )
    updated_raw = raw_content[:raw_start] + replacement + raw_content[raw_end:]
    if updated_raw == raw_content:
        return f"edit: no changes to {_display_path(root, path)}"
    policy_error = _mutation_policy_error(root, path, operation="edit")
    if policy_error is not None:
        return policy_error
    try:
        path.write_bytes(updated_raw.encode("utf-8"))
    except OSError as error:
        return f"edit error: could not write '{_display_path(root, path)}': {error}"
    start_line = content.count("\n", 0, start) + 1
    old_line_count = _line_count(normalized_old_text)
    new_line_count = _line_count(normalized_new_text)
    end_line = start_line + max(old_line_count, new_line_count) - 1
    line_summary = (
        f"line {start_line}"
        if end_line == start_line
        else f"lines {start_line}-{end_line}"
    )
    return f"edit: updated {_display_path(root, path)} ({line_summary})"


def _bash(
    root: Path,
    arguments: Mapping[str, object],
    *,
    max_output_chars: int,
) -> str:
    command = arguments.get("command")
    if not isinstance(command, str) or not command.strip():
        return "bash error: command must be a non-empty string"
    timeout = arguments.get("timeout", 30)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        return "bash error: timeout must be a positive number"
    started_at = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        elapsed = time.perf_counter() - started_at
        output = _process_output(error.stdout, error.stderr, max_output_chars)
        result = f"bash error: command timed out after {timeout} seconds"
        if output:
            result += f"\n{output}"
        return f"{result}\nTook {elapsed:.1f}s"
    elapsed = time.perf_counter() - started_at
    output = _process_output(
        completed.stdout,
        completed.stderr,
        max_output_chars,
    )
    prefix = f"bash: exit code {completed.returncode}"
    result = f"{prefix}\n{output}" if output else prefix
    return f"{result}\nTook {elapsed:.1f}s"


def _process_output(
    stdout: str | bytes | None,
    stderr: str | bytes | None,
    max_output_chars: int,
) -> str:
    parts: list[str] = []
    for label, value in (("stdout", stdout), ("stderr", stderr)):
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        if isinstance(value, str) and value:
            parts.append(f"{label}:\n{value}")
    rendered = "\n".join(parts)
    if len(rendered) <= max_output_chars:
        return rendered
    return rendered[:max_output_chars] + "\n[truncated]"


def _read(
    root: Path,
    arguments: Mapping[str, object],
    *,
    max_lines: int,
    max_output_chars: int,
) -> str:
    path, error = _resolve_argument_path(root, arguments, operation="read")
    if error is not None:
        return error
    assert path is not None
    if not path.is_file():
        return f"read error: '{_display_path(root, path)}' is not a file"
    offset = _positive_integer(arguments.get("offset", 1), "offset")
    limit = _positive_integer(arguments.get("limit", max_lines), "limit")
    column = _positive_integer(arguments.get("column", 1), "column")
    if isinstance(offset, str):
        return f"read error: {offset}"
    if isinstance(limit, str):
        return f"read error: {limit}"
    if isinstance(column, str):
        return f"read error: {column}"
    try:
        with path.open("r", encoding="utf-8") as handle:
            for _ in range(offset - 1):
                if not handle.readline():
                    return f"read: no lines at offset {offset}"
            selected = [
                line.rstrip("\r\n")
                for _ in range(min(limit, max_lines))
                if (line := handle.readline())
            ]
            has_more = bool(handle.read(1))
    except (OSError, UnicodeDecodeError) as error:
        return f"read error: could not read '{_display_path(root, path)}': {error}"
    if not selected:
        return f"read: no lines at offset {offset}"
    next_offset = offset + len(selected)
    return _bounded_lines(
        selected,
        next_offset=next_offset,
        page_offset=offset,
        next_column=column,
        has_more=has_more,
        max_output_chars=max_output_chars,
    )


def _ls(
    root: Path,
    arguments: Mapping[str, object],
    *,
    max_results: int,
    max_output_chars: int,
) -> str:
    path, error = _resolve_argument_path(root, arguments, operation="ls")
    if error is not None:
        return error
    assert path is not None
    if _is_excluded_path(root, path):
        return f"ls error: '{_display_path(root, path)}' is excluded"
    if not path.is_dir():
        return f"ls error: '{_display_path(root, path)}' is not a directory"
    include_hidden = arguments.get("include_hidden", False)
    if not isinstance(include_hidden, bool):
        return "ls error: include_hidden must be a boolean"
    try:
        entries = [
            entry
            for entry in path.iterdir()
            if _visible(entry.name, include_hidden)
            and entry.name.casefold() not in _DEFAULT_EXCLUDED_DIRECTORIES
            and _inside(root, entry)
        ]
    except OSError as error:
        return f"ls error: could not list '{_display_path(root, path)}': {error}"
    entries.sort(key=lambda entry: (not entry.is_dir(), entry.name.casefold()))
    offset = _positive_integer(arguments.get("offset", 1), "offset")
    if isinstance(offset, str):
        return f"ls error: {offset}"
    start = offset - 1
    page = entries[start : start + max_results]
    column = _positive_integer(arguments.get("column", 1), "column")
    if isinstance(column, str):
        return f"ls error: {column}"
    names = [
        f"{entry.name}{'/' if entry.is_dir() else ''}"
        for entry in page
    ]
    if not names:
        return "ls: empty"
    return _bounded_lines(
        names,
        next_offset=offset + len(names),
        page_offset=offset,
        next_column=column,
        has_more=start + len(names) < len(entries),
        max_output_chars=max_output_chars,
    )


def _find(
    root: Path,
    arguments: Mapping[str, object],
    *,
    max_results: int,
    max_output_chars: int,
) -> str:
    path, error = _resolve_argument_path(root, arguments, operation="find")
    if error is not None:
        return error
    assert path is not None
    if _is_excluded_path(root, path):
        return f"find error: '{_display_path(root, path)}' is excluded"
    if not path.is_dir():
        return f"find error: '{_display_path(root, path)}' is not a directory"
    pattern = arguments.get("pattern", "*")
    if not isinstance(pattern, str) or not pattern.strip():
        return "find error: pattern must be a non-empty string"
    include_hidden, hidden_error = _include_hidden(arguments, "find")
    if hidden_error is not None:
        return hidden_error
    offset = _positive_integer(arguments.get("offset", 1), "offset")
    if isinstance(offset, str):
        return f"find error: {offset}"
    column = _positive_integer(arguments.get("column", 1), "column")
    if isinstance(column, str):
        return f"find error: {column}"
    skipped = 0
    results: list[str] = []
    has_more = False
    for candidate in _walk_files(root, path, include_hidden=include_hidden):
        if not fnmatch(candidate.name, pattern):
            continue
        if skipped < offset - 1:
            skipped += 1
            continue
        if len(results) >= max_results:
            has_more = True
            break
        results.append(_display_path(root, candidate))
    return _format_results(
        results,
        operation="find",
        next_offset=offset + len(results),
        page_offset=offset,
        next_column=column,
        max_results=max_results,
        max_output_chars=max_output_chars,
        has_more=has_more,
    )


def _grep(
    root: Path,
    arguments: Mapping[str, object],
    *,
    max_results: int,
    max_output_chars: int,
) -> str:
    pattern = arguments.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        return "grep error: pattern must be a non-empty string"
    case_sensitive = arguments.get("case_sensitive", False)
    if not isinstance(case_sensitive, bool):
        return "grep error: case_sensitive must be a boolean"
    include_hidden, hidden_error = _include_hidden(arguments, "grep")
    if hidden_error is not None:
        return hidden_error
    path, error = _resolve_argument_path(root, arguments, operation="grep")
    if error is not None:
        return error
    assert path is not None
    if _is_excluded_path(root, path):
        return f"grep error: '{_display_path(root, path)}' is excluded"
    offset = _positive_integer(arguments.get("offset", 1), "offset")
    if isinstance(offset, str):
        return f"grep error: {offset}"
    column = _positive_integer(arguments.get("column", 1), "column")
    if isinstance(column, str):
        return f"grep error: {column}"
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        expression = re.compile(pattern, flags)
    except re.error as error:
        return f"grep error: invalid pattern: {error}"
    candidates = (
        (path,)
        if path.is_file()
        else _walk_files(root, path, include_hidden=include_hidden)
    )
    matches: list[str] = []
    skipped = 0
    has_more = False
    for candidate in candidates:
        display = _display_path(root, candidate)
        try:
            with candidate.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    line = line.rstrip("\r\n")
                    if expression.search(line):
                        if skipped < offset - 1:
                            skipped += 1
                            continue
                        if len(matches) >= max_results:
                            has_more = True
                            break
                        matches.append(f"{display}:{line_number}:{line}")
        except (OSError, UnicodeDecodeError):
            continue
        if has_more:
            break
    return _format_results(
        matches,
        operation="grep",
        next_offset=offset + len(matches),
        page_offset=offset,
        next_column=column,
        max_results=max_results,
        max_output_chars=max_output_chars,
        has_more=has_more,
    )


def _resolve_argument_path(
    root: Path,
    arguments: Mapping[str, object],
    *,
    operation: str,
) -> tuple[Path | None, str | None]:
    raw_path = arguments.get("path", ".")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None, f"{operation} error: path must be a non-empty string"
    candidate = (root / raw_path).resolve()
    if not _inside(root, candidate):
        return None, f"{operation} error: path escapes the working directory"
    return candidate, None


def _resolve_mutation_path(
    root: Path,
    arguments: Mapping[str, object],
    *,
    operation: str,
) -> tuple[Path | None, str | None]:
    raw_path = arguments.get("path", ".")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None, f"{operation} error: path must be a non-empty string"
    lexical_path = root / raw_path
    if _contains_symlink(root, lexical_path):
        return None, f"{operation} error: '{_display_path(root, lexical_path)}' is a symlink"
    path = lexical_path.resolve()
    if not _inside(root, path):
        return None, f"{operation} error: path escapes the working directory"
    if _is_excluded_path(root, path):
        return None, f"{operation} error: '{_display_path(root, path)}' is excluded"
    if _is_sensitive_path(root, path):
        return None, f"{operation} error: '{_display_path(root, path)}' is a sensitive target"
    return path, None


def _mutation_policy_error(root: Path, path: Path, *, operation: str) -> str | None:
    if _contains_symlink(root, path):
        return f"{operation} error: '{_display_path(root, path)}' is a symlink"
    if _is_excluded_path(root, path):
        return f"{operation} error: '{_display_path(root, path)}' is excluded"
    if _is_sensitive_path(root, path):
        return f"{operation} error: '{_display_path(root, path)}' is a sensitive target"
    return None


def _contains_symlink(root: Path, candidate: Path) -> bool:
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return False
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return True
    return False


def _is_sensitive_path(root: Path, candidate: Path) -> bool:
    relative = candidate.relative_to(root)
    return relative.name.casefold() in _SENSITIVE_FILE_NAMES


def _normalize_newlines(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _normalize_with_offsets(value: str) -> tuple[str, list[int]]:
    normalized: list[str] = []
    offsets = [0]
    index = 0
    while index < len(value):
        if value[index] == "\r":
            index += 2 if index + 1 < len(value) and value[index + 1] == "\n" else 1
            normalized.append("\n")
        else:
            normalized.append(value[index])
            index += 1
        offsets.append(index)
    return "".join(normalized), offsets


def _replacement_newline(raw_content: str) -> str:
    if "\r\n" in raw_content:
        return "\r\n"
    if "\r" in raw_content:
        return "\r"
    return "\n"


def _replacement_text(
    normalized_text: str,
    raw_match: str,
    raw_content: str,
    raw_start: int,
    raw_end: int,
) -> str:
    newline_forms = re.findall(r"\r\n|\r|\n", raw_match)
    fallback = _local_newline(raw_content, raw_start, raw_end)
    parts = normalized_text.split("\n")
    replacement = parts[0]
    for index, part in enumerate(parts[1:]):
        newline = newline_forms[index] if index < len(newline_forms) else fallback
        replacement += newline + part
    return replacement


def _line_count(value: str) -> int:
    return value.count("\n") + (1 if value and not value.endswith("\n") else 0)


def _count_overlapping(value: str, target: str) -> int:
    return sum(value.startswith(target, index) for index in range(len(value)))


def _local_newline(raw_content: str, raw_start: int, raw_end: int) -> str:
    after = re.match(r"\r\n|\r|\n", raw_content[raw_end:])
    if after is not None:
        return after.group()
    before_matches = list(re.finditer(r"\r\n|\r|\n", raw_content[:raw_start]))
    if before_matches:
        return before_matches[-1].group()
    return _replacement_newline(raw_content)


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _is_excluded_path(root: Path, candidate: Path) -> bool:
    relative = candidate.relative_to(root)
    return any(
        part.casefold() in _DEFAULT_EXCLUDED_DIRECTORIES
        for part in relative.parts
    )


def _walk_files(root: Path, start: Path, *, include_hidden: bool) -> Iterator[Path]:
    for directory, directories, filenames in os.walk(start, followlinks=False):
        directory_path = Path(directory)
        directories[:] = [
            name
            for name in directories
            if _visible(name, include_hidden)
            and name.casefold() not in _DEFAULT_EXCLUDED_DIRECTORIES
            and _inside(root, (directory_path / name).resolve())
        ]
        directories.sort(key=str.casefold)
        for filename in sorted(filenames, key=str.casefold):
            if not _visible(filename, include_hidden):
                continue
            candidate = directory_path / filename
            if _inside(root, candidate.resolve()) and candidate.is_file():
                yield candidate.resolve()


def _visible(name: str, include_hidden: bool) -> bool:
    return include_hidden or not name.startswith(".")


def _include_hidden(
    arguments: Mapping[str, object],
    operation: str,
) -> tuple[bool, str | None]:
    include_hidden = arguments.get("include_hidden", False)
    if not isinstance(include_hidden, bool):
        return False, f"{operation} error: include_hidden must be a boolean"
    return include_hidden, None


def _positive_integer(value: object, name: str) -> int | str:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return f"{name} must be a positive integer"
    return value


def _display_path(root: Path, path: Path) -> str:
    relative = path.relative_to(root).as_posix()
    return relative or "."


def _bounded_lines(
    lines: list[str],
    *,
    next_offset: int,
    page_offset: int,
    next_column: int = 1,
    has_more: bool,
    max_output_chars: int,
) -> str:
    rendered = list(lines)
    if rendered and next_column > 1:
        rendered[0] = rendered[0][next_column - 1 :]
    visible: list[str] = []
    used = 0
    continuation_offset = next_offset
    continuation_column = 1
    for index, line in enumerate(rendered):
        separator = 1 if visible else 0
        if used + separator + len(line) <= max_output_chars:
            visible.append(line)
            used += separator + len(line)
            continue
        remaining = max_output_chars - used - separator
        if remaining > 0:
            visible.append(line[:remaining])
        continuation_offset = page_offset + index
        continuation_column = (next_column + remaining) if index == 0 else remaining + 1
        has_more = True
        break
    text = "\n".join(visible)
    if has_more:
        continuation = f"offset={continuation_offset}"
        if continuation_column > 1:
            continuation += f"&column={continuation_column}"
        text += f"\n[truncated; continue with {continuation}]"
    return text


def _format_results(
    results: list[str],
    *,
    operation: str,
    next_offset: int,
    page_offset: int,
    next_column: int = 1,
    max_results: int,
    max_output_chars: int,
    has_more: bool = False,
) -> str:
    if not results:
        return f"{operation}: no matches"
    limited = results[:max_results]
    return _bounded_lines(
        limited,
        next_offset=next_offset,
        page_offset=page_offset,
        next_column=next_column,
        has_more=has_more,
        max_output_chars=max_output_chars,
    )