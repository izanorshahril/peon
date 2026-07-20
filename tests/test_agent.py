from dataclasses import dataclass
from typing import Sequence

import pytest

from peon.agent import (
    AgentContext,
    AgentMessage,
    ModelResponse,
    ToolCall,
    ToolExecutionContext,
    ToolDefinition,
    Usage,
    run_task,
)
from peon.extensions import ExtensionRegistry
from peon.extensions.filesystem import register_filesystem_tools
from peon.agent import AgentError


@dataclass
class FakeProvider:
    response: str | ModelResponse
    received_messages: tuple[AgentMessage, ...] = ()
    received_tools: tuple[ToolDefinition, ...] = ()
    received_model: str | None = None

    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        self.received_messages = tuple(messages)
        self.received_tools = tuple(tools)
        self.received_model = model
        if isinstance(self.response, ModelResponse):
            return self.response
        return ModelResponse(content=self.response)


class FailingProvider:
    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        raise RuntimeError("connection refused")


@dataclass
class ScriptedProvider:
    responses: list[ModelResponse]
    received_messages: list[tuple[AgentMessage, ...]]
    received_tools: list[tuple[ToolDefinition, ...]]

    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        self.received_messages.append(tuple(messages))
        self.received_tools.append(tuple(tools))
        return self.responses.pop(0)


def build_lookup_registry() -> ExtensionRegistry:
    registry = ExtensionRegistry()
    registry.register_tool(
        name="lookup",
        description="Look up a value.",
        parameters={"type": "object"},
        handler=lambda arguments: f"owner:{arguments['key']}",
    )
    return registry


def test_run_task_forwards_compact_context_and_returns_final_response() -> None:
    provider = FakeProvider(response="Task complete.")
    context = AgentContext(
        messages=[AgentMessage(role="system", content="Be concise.")]
    )

    result = run_task(
        "Summarize the repository.",
        provider,
        context=context,
        model="fake-model",
    )

    assert result == "Task complete."
    assert provider.received_messages == (
        AgentMessage(role="system", content="Be concise."),
        AgentMessage(role="user", content="Summarize the repository."),
    )
    assert provider.received_model == "fake-model"
    assert context.messages[-1] == AgentMessage(
        role="assistant", content="Task complete."
    )


def test_run_task_can_preserve_task_whitespace() -> None:
    provider = FakeProvider(response="Task complete.")

    run_task(
        "  Keep this text.\n",
        provider,
        preserve_task_whitespace=True,
    )

    assert provider.received_messages == (
        AgentMessage(role="user", content="  Keep this text.\n"),
    )


def test_run_task_forwards_available_tools_to_provider() -> None:
    provider = FakeProvider(response="Task complete.")
    tools = [
        ToolDefinition(
            name="lookup",
            description="Look up a value.",
            parameters={"type": "object"},
        )
    ]

    run_task("Look up the value.", provider, tools=tools)

    assert provider.received_tools == tuple(tools)


def test_run_task_returns_a_normalized_tool_call() -> None:
    tool_call = ToolCall(
        name="lookup",
        arguments={"key": "owner"},
        call_id="call-1",
    )
    provider = FakeProvider(response=ModelResponse(tool_call=tool_call))

    result = run_task("Look up the owner.", provider)

    assert result == tool_call


def test_run_task_exposes_provider_failure_as_agent_error() -> None:
    try:
        run_task("Do work.", FailingProvider())
    except AgentError as error:
        assert str(error) == "provider request failed: connection refused"
    else:
        raise AssertionError("run_task should report provider failures")


def test_run_task_executes_tool_and_continues_until_final_response() -> None:
    provider = ScriptedProvider(
        responses=[
            ModelResponse(
                tool_call=ToolCall(
                    name="lookup",
                    arguments={"key": "owner"},
                    call_id="call-1",
                )
            ),
            ModelResponse(content="The owner is Peon."),
        ],
        received_messages=[],
        received_tools=[],
    )
    registry = build_lookup_registry()
    context = AgentContext()

    result = run_task(
        "Who owns the project?",
        provider,
        context=context,
        executor=registry,
    )

    assert result == "The owner is Peon."
    assert provider.received_tools == [registry.tools, registry.tools]
    assert provider.received_messages[1] == (
        AgentMessage(role="user", content="Who owns the project?"),
        AgentMessage(
            role="assistant",
            content="",
            tool_call=ToolCall(
                name="lookup",
                arguments={"key": "owner"},
                call_id="call-1",
            ),
        ),
        AgentMessage(
            role="tool",
            content="owner:owner",
            tool_call_id="call-1",
        ),
    )
    assert context.messages == list(provider.received_messages[1]) + [
        AgentMessage(role="assistant", content="The owner is Peon."),
    ]


def test_run_task_reports_usage_for_each_provider_request() -> None:
    provider = ScriptedProvider(
        responses=[
            ModelResponse(
                tool_call=ToolCall(
                    name="lookup",
                    arguments={"key": "owner"},
                    call_id="call-usage",
                ),
                usage=Usage(input_tokens=10, output_tokens=2),
            ),
            ModelResponse(
                content="The owner is Peon.",
                usage=Usage(input_tokens=20, output_tokens=4, cache_tokens=3),
            ),
        ],
        received_messages=[],
        received_tools=[],
    )
    usage: list[Usage | None] = []

    result = run_task(
        "Who owns the project?",
        provider,
        context=AgentContext(),
        executor=build_lookup_registry(),
        on_usage=usage.append,
    )

    assert result == "The owner is Peon."
    assert usage == [
        Usage(input_tokens=10, output_tokens=2),
        Usage(input_tokens=20, output_tokens=4, cache_tokens=3),
    ]


def test_run_task_executes_registered_filesystem_edit_and_records_result(tmp_path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("before\n", encoding="utf-8")
    provider = ScriptedProvider(
        responses=[
            ModelResponse(
                tool_call=ToolCall(
                    name="edit",
                    arguments={
                        "path": "notes.txt",
                        "old_text": "before",
                        "new_text": "after",
                    },
                    call_id="edit-1",
                )
            ),
            ModelResponse(content="Updated the note."),
        ],
        received_messages=[],
        received_tools=[],
    )
    registry = ExtensionRegistry()
    register_filesystem_tools(registry, root=tmp_path)
    context = AgentContext()

    result = run_task(
        "Update the note.",
        provider,
        context=context,
        executor=registry,
    )

    assert result == "Updated the note."
    assert target.read_text(encoding="utf-8") == "after\n"
    assert context.messages[-2:] == [
        AgentMessage(
            role="tool",
            content="edit: updated notes.txt (line 1)",
            tool_call_id="edit-1",
        ),
        AgentMessage(role="assistant", content="Updated the note."),
    ]


def test_run_task_executes_registered_filesystem_write(tmp_path) -> None:
    provider = ScriptedProvider(
        responses=[
            ModelResponse(
                tool_call=ToolCall(
                    name="write",
                    arguments={"path": "notes.txt", "content": "saved\n"},
                    call_id="write-1",
                )
            ),
            ModelResponse(content="Saved the note."),
        ],
        received_messages=[],
        received_tools=[],
    )
    registry = ExtensionRegistry()
    register_filesystem_tools(registry, root=tmp_path)
    context = AgentContext()

    result = run_task(
        "Save the note.",
        provider,
        context=context,
        executor=registry,
    )

    assert result == "Saved the note."
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "saved\n"
    assert context.messages[-2:] == [
        AgentMessage(
            role="tool",
            content="write: wrote 6 bytes and 1 lines to notes.txt",
            tool_call_id="write-1",
        ),
        AgentMessage(role="assistant", content="Saved the note."),
    ]


def test_run_task_propagates_tool_cancellation_context() -> None:
    registry = ExtensionRegistry()

    def cancel_tool(
        arguments: dict[str, object],
        execution_context: ToolExecutionContext,
    ) -> str:
        del arguments
        execution_context.cancel()
        return "cancelled by tool"

    registry.register_tool(
        name="cancel",
        description="Cancel the current operation.",
        parameters={"type": "object"},
        handler=cancel_tool,
    )
    provider = ScriptedProvider(
        responses=[
            ModelResponse(
                tool_call=ToolCall(
                    name="cancel",
                    arguments={},
                    call_id="cancel-1",
                )
            )
        ],
        received_messages=[],
        received_tools=[],
    )
    context = AgentContext()
    execution_context = ToolExecutionContext()

    with pytest.raises(AgentError, match="tool execution cancelled"):
        run_task(
            "Stop the operation.",
            provider,
            context=context,
            executor=registry,
            execution_context=execution_context,
        )

    assert context.messages[-1] == AgentMessage(
        role="tool",
        content="cancelled by tool",
        tool_call_id="cancel-1",
    )


def test_run_task_forwards_executor_tools_to_provider() -> None:
    provider = ScriptedProvider(
        responses=[ModelResponse(content="Done.")],
        received_messages=[],
        received_tools=[],
    )
    registry = build_lookup_registry()

    run_task("Look up the owner.", provider, executor=registry)

    assert provider.received_tools == [registry.tools]


def test_run_task_reports_unknown_tool_failures() -> None:
    provider = ScriptedProvider(
        responses=[
            ModelResponse(
                tool_call=ToolCall(name="missing", arguments={})
            )
        ],
        received_messages=[],
        received_tools=[],
    )
    context = AgentContext()

    with pytest.raises(AgentError, match="tool 'missing'.*not registered"):
        run_task(
            "Use the missing tool.",
            provider,
            context=context,
            executor=build_lookup_registry(),
        )

    assert context.messages[-1] == AgentMessage(
        role="tool",
        content="tool error: tool 'missing' is not registered",
    )


def test_run_task_rejects_invalid_tool_arguments() -> None:
    provider = ScriptedProvider(
        responses=[
            ModelResponse(
                tool_call=ToolCall(
                    name="lookup",
                    arguments=[],  # type: ignore[arg-type]
                )
            )
        ],
        received_messages=[],
        received_tools=[],
    )

    with pytest.raises(AgentError, match="arguments must be an object"):
        run_task("Look up the owner.", provider, executor=build_lookup_registry())


def test_run_task_reports_continuation_provider_failures() -> None:
    class ContinuationFailureProvider(ScriptedProvider):
        def complete(
            self,
            *,
            messages: Sequence[AgentMessage],
            tools: Sequence[ToolDefinition] = (),
            model: str | None = None,
        ) -> ModelResponse:
            self.received_messages.append(tuple(messages))
            if len(self.received_messages) == 1:
                return ModelResponse(
                    tool_call=ToolCall(name="lookup", arguments={"key": "owner"})
                )
            raise RuntimeError("continuation unavailable")

    provider = ContinuationFailureProvider(
        responses=[], received_messages=[], received_tools=[]
    )

    with pytest.raises(
        AgentError,
        match="provider request failed: continuation unavailable",
    ):
        run_task("Look up the owner.", provider, executor=build_lookup_registry())


def test_run_task_reports_exhausted_tool_call_limit() -> None:
    provider = ScriptedProvider(
        responses=[
            ModelResponse(
                tool_call=ToolCall(
                    name="lookup", arguments={"key": "owner"}
                )
            ),
            ModelResponse(
                tool_call=ToolCall(
                    name="lookup", arguments={"key": "owner"}
                )
            ),
        ],
        received_messages=[],
        received_tools=[],
    )

    with pytest.raises(AgentError, match="maximum tool-call limit exceeded"):
        run_task(
            "Keep looking.",
            provider,
            executor=build_lookup_registry(),
            max_tool_calls=1,
        )