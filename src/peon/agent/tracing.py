"""Provider-neutral metadata tracing contracts."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Protocol

logger = logging.getLogger(__name__)
UtcClock = Callable[[], datetime]


class TraceSink(Protocol):
    """Receive metadata-only operation records."""

    def emit(self, record: Mapping[str, object]) -> None:
        """Export one trace record."""
        ...


@dataclass(frozen=True, slots=True)
class TraceContext:
    session_id: str | None = None
    run_id: str | None = None
    turn_id: str | None = None

    def fields(self) -> dict[str, str]:
        return {
            key: value
            for key, value in {
                "session_id": self.session_id,
                "run_id": self.run_id,
                "turn_id": self.turn_id,
            }.items()
            if value is not None
        }


def emit_trace(
    sink: TraceSink | None,
    *,
    started_at: float,
    ended_at: float,
    operation: str,
    outcome: str,
    context: TraceContext | None = None,
    utc_clock: UtcClock = lambda: datetime.now(timezone.utc),
    fields: Mapping[str, object] | None = None,
) -> None:
    """Emit one isolated trace record without affecting the operation."""
    if sink is None:
        return
    record: dict[str, object] = {
        "schema_version": 1,
        "timestamp": utc_clock().isoformat(),
        "duration": ended_at - started_at,
        "operation": operation,
        "outcome": outcome,
    }
    if context is not None:
        record.update(context.fields())
    if fields is not None:
        record.update(fields)
    try:
        sink.emit(record)
    except Exception:
        logger.exception("trace export failed")
