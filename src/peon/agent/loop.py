"""The minimal bounded agent orchestration boundary."""

from collections.abc import Callable, Mapping, Sequence

from .runtime_errors import AgentError

from .executor import ToolExecutionContext, ToolExecutor
from .models import AgentContext, AgentMessage, ToolCall, ToolDefinition, Usage
from .provider_protocol import ModelProvider


def run_task(
    task: str,
    provider: ModelProvider,
    *,
    context: AgentContext | None = None,
    tools: Sequence[ToolDefinition] = (),
    executor: ToolExecutor | None = None,
    max_tool_calls: int = 8,
    model: str | None = None,
    on_message: Callable[[AgentMessage], None] | None = None,
    on_usage: Callable[[Usage | None], None] | None = None,
    preserve_task_whitespace: bool = False,
    execution_context: ToolExecutionContext | None = None,
) -> str | ToolCall:
    """Run one task against an injected provider and return its response."""
    normalized_task = task if preserve_task_whitespace else task.strip()
    if not normalized_task.strip():
        raise AgentError("task is required")
    if max_tool_calls < 1:
        raise AgentError("max_tool_calls must be at least 1")

    active_context = context if context is not None else AgentContext()
    user_message = AgentMessage(role="user", content=normalized_task)
    active_context.add(user_message)
    if on_message is not None:
        on_message(user_message)
    available_tools = tuple(tools)
    if executor is not None and not available_tools:
        available_tools = tuple(executor.tools)
    tool_calls = 0
    while True:
        try:
            response = provider.complete(
                messages=active_context.messages,
                tools=available_tools,
                model=model,
            )
        except Exception as error:
            raise AgentError(f"provider request failed: {error}") from error
        if on_usage is not None:
            on_usage(response.usage)

        if response.tool_call is not None:
            if executor is None:
                return response.tool_call
            tool_calls += 1
            if tool_calls > max_tool_calls:
                raise AgentError("maximum tool-call limit exceeded")
            _continue_with_tool_call(
                active_context,
                executor,
                response.tool_call,
                thinking=response.thinking,
                on_message=on_message,
                execution_context=execution_context,
            )
            if execution_context is not None and execution_context.cancelled:
                raise AgentError("tool execution cancelled")
            continue

        response_text = response.content.strip()
        if not response_text:
            raise AgentError("provider returned an empty response")

        assistant_message = AgentMessage(
            role="assistant",
            content=response_text,
            thinking=response.thinking or None,
        )
        active_context.add(assistant_message)
        if on_message is not None:
            on_message(assistant_message)
        return response_text


def _continue_with_tool_call(
    context: AgentContext,
    executor: ToolExecutor,
    tool_call: ToolCall,
    *,
    thinking: str = "",
    on_message: Callable[[AgentMessage], None] | None = None,
    execution_context: ToolExecutionContext | None = None,
) -> None:
    if not isinstance(tool_call.arguments, Mapping):
        raise AgentError(
            f"tool '{tool_call.name}' arguments must be an object"
        )
    assistant_message = AgentMessage(
        role="assistant",
        content="",
        thinking=thinking or None,
        tool_call=tool_call,
    )
    context.add(assistant_message)
    if on_message is not None:
        on_message(assistant_message)
    try:
        contextual_invoke = getattr(executor, "invoke_with_context", None)
        if execution_context is not None and callable(contextual_invoke):
            result = contextual_invoke(
                tool_call.name,
                tool_call.arguments,
                execution_context,
            )
        else:
            result = executor.invoke(tool_call.name, tool_call.arguments)
    except Exception as error:
        tool_message = AgentMessage(
            role="tool",
            content=f"tool error: {error}",
            tool_call_id=tool_call.call_id,
        )
        context.add(tool_message)
        if on_message is not None:
            on_message(tool_message)
        raise AgentError(
            f"tool '{tool_call.name}' failed: {error}"
        ) from error
    if not isinstance(result, str):
        tool_message = AgentMessage(
            role="tool",
            content=f"tool error: '{tool_call.name}' returned a non-text result",
            tool_call_id=tool_call.call_id,
        )
        context.add(tool_message)
        if on_message is not None:
            on_message(tool_message)
        raise AgentError(f"tool '{tool_call.name}' returned a non-text result")
    tool_message = AgentMessage(
        role="tool",
        content=result,
        tool_call_id=tool_call.call_id,
    )
    context.add(tool_message)
    if on_message is not None:
        on_message(tool_message)