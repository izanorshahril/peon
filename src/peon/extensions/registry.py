"""Small in-process registry for tools, skills, and lifecycle hooks."""

from collections.abc import Callable, Mapping, Sequence

from peon.agent import ToolDefinition

from .errors import ExtensionError

ToolHandler = Callable[[Mapping[str, object]], object]
SkillInstaller = Callable[["ExtensionRegistry"], None]
LifecycleHandler = Callable[[], None]


class ExtensionRegistry:
    """Register and invoke extension capabilities in registration order."""

    def __init__(self) -> None:
        self._tools: dict[str, tuple[ToolDefinition, ToolHandler]] = {}
        self._hooks: dict[str, list[LifecycleHandler]] = {}

    @property
    def tools(self) -> tuple[ToolDefinition, ...]:
        """Return model-facing tool definitions in registration order."""
        return tuple(definition for definition, handler in self._tools.values())

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
        )

    def register_skill(self, name: str, installer: SkillInstaller) -> None:
        """Install a named group of related tools into this registry."""
        if not name.strip():
            raise ExtensionError("skill name is required")
        try:
            installer(self)
        except ExtensionError:
            raise
        except Exception as error:
            raise ExtensionError(f"skill '{name}' failed: {error}") from error

    def invoke(self, name: str, arguments: Mapping[str, object]) -> str:
        """Invoke a registered tool with model-supplied arguments."""
        registered = self._tools.get(name)
        if registered is None:
            raise ExtensionError(f"tool '{name}' is not registered")
        _, handler = registered
        try:
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