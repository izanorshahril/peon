"""Small in-process registry for tools, skills, and lifecycle hooks."""

from collections.abc import Callable, Mapping, Sequence
import inspect
from pathlib import Path

from peon.agent import ToolDefinition, ToolExecutionContext

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

    def __init__(self) -> None:
        self._tools: dict[
            str,
            tuple[ToolDefinition, ToolHandler, bool],
        ] = {}
        self._skills: list[str] = []
        self._hooks: dict[str, list[LifecycleHandler]] = {}

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
            try:
                handler()
            except Exception as error:
                raise ExtensionError(f"event '{event}' failed: {error}") from error


def _accepts_context(handler: ToolHandler) -> bool:
    try:
        inspect.signature(handler).bind({}, ToolExecutionContext())
    except (TypeError, ValueError):
        return False
    return True