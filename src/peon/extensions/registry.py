"""Small in-process registry for tools, skills, and lifecycle hooks."""

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
import inspect
from pathlib import Path

from peon.agent import ToolDefinition, ToolExecutionContext, TraceContext, TraceSink
from peon.agent.tracing import emit_trace

from .errors import ExtensionError

ToolHandler = Callable[..., object]
SkillInstaller = Callable[["ExtensionRegistry"], None]
LifecycleHandler = Callable[[], None]


def discover_skill_names(root: Path | None = None) -> tuple[str, ...]:
    """Discover skill names without loading or executing their instructions."""
    skills_root = (root or Path.cwd()) / ".agents" / "skills"
    if not skills_root.is_dir():
        return ()
    return tuple(
        path.name
        for path in sorted(skills_root.iterdir(), key=lambda item: item.name.casefold())
        if path.is_dir() and (path / "SKILL.md").is_file()
    )


class ExtensionRegistry:
    """Register and invoke extension capabilities in registration order."""

    def __init__(
        self,
        *,
        trace_sink: TraceSink | None = None,
        trace_context: TraceContext | None = None,
        trace_clock: Callable[[], float] | None = None,
        trace_utc_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._tools: dict[
            str,
            tuple[ToolDefinition, ToolHandler, bool],
        ] = {}
        self._skills: list[str] = []
        self._hooks: dict[str, list[LifecycleHandler]] = {}
        self._trace_sink = trace_sink
        self._trace_context = trace_context
        self._trace_clock = trace_clock
        self._trace_utc_clock = trace_utc_clock

    @property
    def tools(self) -> tuple[ToolDefinition, ...]:
        """Return model-facing tool definitions in registration order."""
        return tuple(
            definition
            for definition, _handler, _accepts_context in self._tools.values()
        )

    @property
    def skills(self) -> tuple[str, ...]:
        """Return registered skill names in registration order."""
        return tuple(self._skills)

    def register_tool(
        self,
        *,
        name: str,
        description: str,
        parameters: Mapping[str, object],
        handler: ToolHandler,
    ) -> None:
        """Register one tool and its callable handler."""
        if not name.strip():
            raise ExtensionError("tool name is required")
        if name in self._tools:
            raise ExtensionError(f"tool '{name}' is already registered")
        self._tools[name] = (
            ToolDefinition(
                name=name,
                description=description,
                parameters=parameters,
            ),
            handler,
            _accepts_context(handler),
        )

    def register_skill(self, name: str, installer: SkillInstaller) -> None:
        """Install a named group of related tools into this registry."""
        if not name.strip():
            raise ExtensionError("skill name is required")
        if name in self._skills:
            raise ExtensionError(f"skill '{name}' is already registered")
        try:
            installer(self)
        except ExtensionError:
            raise
        except Exception as error:
            raise ExtensionError(f"skill '{name}' failed: {error}") from error
        self._skills.append(name)

    def invoke(self, name: str, arguments: Mapping[str, object]) -> str:
        return self._invoke(name, arguments, None)

    def invoke_with_context(
        self,
        name: str,
        arguments: Mapping[str, object],
        context: ToolExecutionContext,
    ) -> str:
        return self._invoke(name, arguments, context)

    def _invoke(
        self,
        name: str,
        arguments: Mapping[str, object],
        context: ToolExecutionContext | None,
    ) -> str:
        """Invoke a registered tool with model-supplied arguments."""
        registered = self._tools.get(name)
        if registered is None:
            raise ExtensionError(f"tool '{name}' is not registered")
        _, handler, accepts_context = registered
        try:
            if context is not None and accepts_context:
                result = handler(arguments, context)
            else:
                result = handler(arguments)
        except Exception as error:
            raise ExtensionError(f"tool '{name}' failed: {error}") from error
        if not isinstance(result, str):
            raise ExtensionError(f"tool '{name}' returned a non-text result")
        return result

    def on(self, event: str, handler: LifecycleHandler) -> None:
        """Register a no-argument handler for a lifecycle event."""
        if not event.strip():
            raise ExtensionError("event name is required")
        self._hooks.setdefault(event, []).append(handler)

    def emit(self, event: str) -> None:
        """Invoke lifecycle handlers in registration order."""
        for handler in self._hooks.get(event, ()):
            active_trace_clock = (
                self._trace_clock
                if self._trace_sink is not None and self._trace_clock is not None
                else None
            )
            started_at = (
                active_trace_clock() if active_trace_clock is not None else None
            )
            try:
                handler()
            except Exception as error:
                if started_at is not None and active_trace_clock is not None:
                    emit_trace(
                        self._trace_sink,
                        started_at=started_at,
                        ended_at=active_trace_clock(),
                        operation="extension.hook",
                        outcome="error",
                        context=self._trace_context,
                        utc_clock=self._trace_utc_clock or _utc_now,
                        fields={"hook": event},
                    )
                raise ExtensionError(f"event '{event}' failed: {error}") from error
            if started_at is not None and active_trace_clock is not None:
                emit_trace(
                    self._trace_sink,
                    started_at=started_at,
                    ended_at=active_trace_clock(),
                    operation="extension.hook",
                    outcome="success",
                    context=self._trace_context,
                    utc_clock=self._trace_utc_clock or _utc_now,
                    fields={"hook": event},
                )


def _accepts_context(handler: ToolHandler) -> bool:
    try:
        inspect.signature(handler).bind({}, ToolExecutionContext())
    except (TypeError, ValueError):
        return False
    return True


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
