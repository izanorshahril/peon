import pytest
from collections.abc import Sequence

from peon.agent import AgentMessage, ModelResponse, ToolCall, ToolDefinition, run_task
from peon.extensions import (
    ExtensionError,
    ExtensionRegistry,
    discover_skill_names,
    register_sample_tools,
)


class ScriptedProvider:
    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = responses
        self.messages: list[tuple[AgentMessage, ...]] = []

    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        self.messages.append(tuple(messages))
        return self.responses.pop(0)


def test_sample_extension_runs_through_task_continuation_path() -> None:
    registry = ExtensionRegistry()
    register_sample_tools(registry)
    provider = ScriptedProvider(
        [
            ModelResponse(
                tool_call=ToolCall(
                    name="word_count",
                    arguments={"text": "Peon stays small."},
                    call_id="call-1",
                )
            ),
            ModelResponse(content="The text contains 3 words."),
        ]
    )

    result = run_task(
        "How many words are in the sample?",
        provider,
        executor=registry,
    )

    assert result == "The text contains 3 words."
    assert registry.invoke("word_count", {"text": "Peon stays small."}) == (
        "word count: 3"
    )
    assert provider.messages[1][-1].content == "word count: 3"


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


def test_registry_exposes_registered_skill_names() -> None:
    registry = ExtensionRegistry()

    registry.register_skill("notes", lambda target: None)

    assert registry.skills == ("notes",)

    with pytest.raises(ExtensionError, match="skill 'notes' is already registered"):
        registry.register_skill("notes", lambda target: None)


def test_discover_skill_names_reads_metadata_without_loading_skills(tmp_path) -> None:
    skill = tmp_path / ".agents" / "skills" / "notes"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Notes\n", encoding="utf-8")
    ignored = tmp_path / ".agents" / "skills" / "ignored"
    ignored.mkdir()

    assert discover_skill_names(tmp_path) == ("notes",)


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