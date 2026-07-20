"""Application-owned performance trace sinks."""

from collections.abc import Mapping
import json
from pathlib import Path
from threading import Lock
from typing import TextIO

from peon.agent import TraceSink


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
