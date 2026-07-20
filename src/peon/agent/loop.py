"""The minimal bounded agent orchestration boundary."""

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone

from .runtime_errors import AgentError

from .executor import ToolExecutionContext, ToolExecutor
from .models import AgentContext, AgentMessage, ToolCall, ToolDefinition, Usage
from .provider_protocol import ModelProvider
from .tracing import TraceContext, TraceSink, emit_trace


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
    trace_sink: TraceSink | None = None,
    trace_context: TraceContext | None = None,
    trace_provider: str | None = None,
    trace_model: str | None = None,
    trace_clock: Callable[[], float] | None = None,
    trace_utc_clock: Callable[[], datetime] | None = None,
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
    active_trace_clock = (
        trace_clock
        if trace_sink is not None and trace_clock is not None
        else None
    )
    while True:
        provider_started_at = (
            active_trace_clock() if active_trace_clock is not None else 0.0
        )
        try:
            response = provider.complete(
                messages=active_context.messages,
                tools=available_tools,
                model=model,
            )
        except Exception as error:
            if active_trace_clock is not None:
                emit_trace(
                    trace_sink,
                    started_at=provider_started_at,
                    ended_at=active_trace_clock(),
                    operation="provider.request",
                    outcome="error",
                    context=trace_context,
                    utc_clock=trace_utc_clock or _utc_now,
                    fields=_provider_trace_fields(trace_provider, trace_model),
                )
            raise AgentError(f"provider request failed: {error}") from error
        if active_trace_clock is not None:
            emit_trace(
                trace_sink,
                started_at=provider_started_at,
                ended_at=active_trace_clock(),
                operation="provider.request",
                outcome=(
                    "cancelled"
                    if execution_context is not None
                    and execution_context.cancelled
                    else "success"
                ),
                context=trace_context,
                utc_clock=trace_utc_clock or _utc_now,
                fields=_provider_trace_fields(trace_provider, trace_model),
            )
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
                trace_sink=trace_sink,
                trace_context=trace_context,
                trace_clock=active_trace_clock,
                trace_utc_clock=trace_utc_clock,
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
    trace_sink: TraceSink | None = None,
    trace_context: TraceContext | None = None,
    trace_clock: Callable[[], float] | None = None,
    trace_utc_clock: Callable[[], datetime] | None = None,
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
    active_trace_clock = (
        trace_clock
        if trace_sink is not None and trace_clock is not None
        else None
    )
    tool_started_at = (
        active_trace_clock() if active_trace_clock is not None else 0.0
    )
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
        if active_trace_clock is not None:
            emit_trace(
                trace_sink,
                started_at=tool_started_at,
                ended_at=active_trace_clock(),
                operation="tool.invoke",
                outcome=(
                    "cancelled"
                    if execution_context is not None
                    and execution_context.cancelled
                    else "error"
                ),
                context=trace_context,
                utc_clock=trace_utc_clock or _utc_now,
                fields={"tool": tool_call.name},
            )
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
        if active_trace_clock is not None:
            emit_trace(
                trace_sink,
                started_at=tool_started_at,
                ended_at=active_trace_clock(),
                operation="tool.invoke",
                outcome="error",
                context=trace_context,
                utc_clock=trace_utc_clock or _utc_now,
                fields={"tool": tool_call.name},
            )
        tool_message = AgentMessage(
            role="tool",
            content=f"tool error: '{tool_call.name}' returned a non-text result",
            tool_call_id=tool_call.call_id,
        )
        context.add(tool_message)
        if on_message is not None:
            on_message(tool_message)
        raise AgentError(f"tool '{tool_call.name}' returned a non-text result")
    if active_trace_clock is not None:
        emit_trace(
            trace_sink,
            started_at=tool_started_at,
            ended_at=active_trace_clock(),
            operation="tool.invoke",
            outcome=(
                "cancelled"
                if execution_context is not None
                and execution_context.cancelled
                else "success"
            ),
            context=trace_context,
            utc_clock=trace_utc_clock or _utc_now,
            fields={"tool": tool_call.name},
        )
    tool_message = AgentMessage(
        role="tool",
        content=result,
        tool_call_id=tool_call.call_id,
    )
    context.add(tool_message)
    if on_message is not None:
        on_message(tool_message)


def _provider_trace_fields(
    provider: str | None,
    model: str | None,
) -> dict[str, object]:
    return {
        key: value
        for key, value in {"provider": provider, "model": model}.items()
        if value is not None
    }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
