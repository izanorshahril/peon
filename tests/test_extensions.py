import pytest

from peon.agent import ToolDefinition
from peon.extensions import ExtensionError, ExtensionRegistry


def test_registry_registers_and_invokes_a_tool_through_public_seam() -> None:
    registry = ExtensionRegistry()

    registry.register_tool(
        name="lookup",
        description="Look up a value.",
        parameters={"type": "object"},
        handler=lambda arguments: f"value:{arguments['key']}",
    )

    assert registry.tools == (
        ToolDefinition(
            name="lookup",
            description="Look up a value.",
            parameters={"type": "object"},
        ),
    )
    assert registry.invoke("lookup", {"key": "owner"}) == "value:owner"


def test_skill_can_register_multiple_related_tools() -> None:
    registry = ExtensionRegistry()

    def install_note_tools(target: ExtensionRegistry) -> None:
        target.register_tool(
            name="add_note",
            description="Add a note.",
            parameters={"type": "object"},
            handler=lambda arguments: f"added:{arguments['text']}",
        )
        target.register_tool(
            name="list_notes",
            description="List notes.",
            parameters={"type": "object"},
            handler=lambda arguments: "notes:empty",
        )

    registry.register_skill("notes", install_note_tools)

    assert [tool.name for tool in registry.tools] == ["add_note", "list_notes"]
    assert registry.invoke("add_note", {"text": "remember this"}) == (
        "added:remember this"
    )
    assert registry.invoke("list_notes", {}) == "notes:empty"


def test_registry_dispatches_lifecycle_hooks() -> None:
    registry = ExtensionRegistry()
    observed: list[str] = []

    registry.on("session_start", lambda: observed.append("started"))
    registry.emit("session_start")

    assert observed == ["started"]


def test_registry_reports_unknown_duplicate_and_handler_failures() -> None:
    registry = ExtensionRegistry()
    registry.register_tool(
        name="lookup",
        description="Look up a value.",
        parameters={},
        handler=lambda arguments: "ok",
    )

    with pytest.raises(ExtensionError, match="tool 'missing' is not registered"):
        registry.invoke("missing", {})
    with pytest.raises(ExtensionError, match="tool 'lookup' is already registered"):
        registry.register_tool(
            name="lookup",
            description="Another lookup.",
            parameters={},
            handler=lambda arguments: "again",
        )

    def failing_handler(arguments):
        raise ValueError("bad input")

    registry.register_tool(
        name="fail",
        description="Fail.",
        parameters={},
        handler=failing_handler,
    )
    with pytest.raises(ExtensionError, match="tool 'fail' failed: bad input"):
        registry.invoke("fail", {})


def test_registry_reports_non_text_tool_results() -> None:
    registry = ExtensionRegistry()
    registry.register_tool(
        name="number",
        description="Return a number.",
        parameters={},
        handler=lambda arguments: 42,
    )

    with pytest.raises(ExtensionError, match="returned a non-text result"):
        registry.invoke("number", {})


def test_registry_reports_skill_and_lifecycle_failures() -> None:
    registry = ExtensionRegistry()

    with pytest.raises(ExtensionError, match="skill 'broken' failed: install failed"):
        registry.register_skill(
            "broken",
            lambda target: (_ for _ in ()).throw(RuntimeError("install failed")),
        )

    registry.on("session_end", lambda: (_ for _ in ()).throw(ValueError("cleanup failed")))
    with pytest.raises(
        ExtensionError,
        match="event 'session_end' failed: cleanup failed",
    ):
        registry.emit("session_end")