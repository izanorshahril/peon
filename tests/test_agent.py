from dataclasses import dataclass
from typing import Sequence

import pytest

from peon.agent import (
    AgentContext,
    AgentMessage,
    ModelResponse,
    ToolCall,
    ToolDefinition,
    run_task,
)
from peon.extensions import ExtensionRegistry
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

    with pytest.raises(AgentError, match="tool 'missing'.*not registered"):
        run_task("Use the missing tool.", provider, executor=build_lookup_registry())


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