"""Read-only, cwd-bound filesystem tools for the application registry."""

from collections.abc import Iterator, Mapping
from fnmatch import fnmatch
import os
from pathlib import Path
import re

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


def register_filesystem_tools(
    registry: ExtensionRegistry,
    *,
    root: Path | None = None,
    max_lines: int = 200,
    max_results: int = 100,
    max_output_chars: int = 12000,
) -> None:
    """Register read-only tools rooted at one working directory."""
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
            and entry.name not in _DEFAULT_EXCLUDED_DIRECTORIES
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


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _is_excluded_path(root: Path, candidate: Path) -> bool:
    relative = candidate.relative_to(root)
    return any(part in _DEFAULT_EXCLUDED_DIRECTORIES for part in relative.parts)


def _walk_files(root: Path, start: Path, *, include_hidden: bool) -> Iterator[Path]:
    for directory, directories, filenames in os.walk(start, followlinks=False):
        directory_path = Path(directory)
        directories[:] = [
            name
            for name in directories
            if _visible(name, include_hidden)
            and name not in _DEFAULT_EXCLUDED_DIRECTORIES
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