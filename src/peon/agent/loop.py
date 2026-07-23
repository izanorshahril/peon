"""The minimal bounded agent orchestration boundary."""

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
import json
import time
from typing import Any, cast

from .runtime_errors import AgentError, LimitExceededError

from .executor import ToolExecutionContext, ToolExecutor
from .models import (
	AgentContext,
	AgentMessage,
	ModelResponse,
	ModelStreamChunk,
	ToolCall,
	ToolDefinition,
	Usage,
)
from .provider_protocol import ModelProvider, StreamingModelProvider
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
    on_stream_chunk: Callable[[ModelStreamChunk], None] | None = None,
    trace_sink: TraceSink | None = None,
    trace_context: TraceContext | None = None,
    trace_provider: str | None = None,
    trace_model: str | None = None,
    trace_clock: Callable[[], float] | None = None,
    trace_utc_clock: Callable[[], datetime] | None = None,
    preserve_task_whitespace: bool = False,
    execution_context: ToolExecutionContext | None = None,
    limits: Any = None,
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
    provider_calls = 0
    tool_calls = 0
    acc_input_tokens = 0
    acc_output_tokens = 0
    acc_total_tokens = 0
    acc_cost = 0.0
    active_trace_clock = (
        trace_clock
        if trace_sink is not None and trace_clock is not None
        else None
    )
    clock_fn = active_trace_clock or time.monotonic
    start_time = (
        clock_fn()
        if (limits is not None and limits.max_elapsed_seconds is not None)
        else 0.0
    )
    while True:
        if limits is not None:
            if limits.max_elapsed_seconds is not None:
                now_time = clock_fn()
                if (now_time - start_time) > limits.max_elapsed_seconds:
                    raise LimitExceededError(
                        "max_elapsed_seconds_exceeded", "elapsed time limit exceeded"
                    )
            if (
                limits.max_provider_calls is not None
                and provider_calls >= limits.max_provider_calls
            ):
                raise LimitExceededError(
                    "max_provider_calls_exceeded",
                    "maximum provider-call limit exceeded",
                )

        provider_started_at = (
            active_trace_clock() if active_trace_clock is not None else 0.0
        )
        provider_calls += 1
        try:
            if hasattr(provider, "stream") and callable(getattr(provider, "stream")):
                streaming_provider = cast(StreamingModelProvider, provider)
                content_parts: list[str] = []
                thinking_parts: list[str] = []
                tool_calls_map: dict[int, dict[str, str]] = {}
                final_usage: Usage | None = None

                chunks = streaming_provider.stream(
                    messages=active_context.messages,
                    tools=available_tools,
                    model=model,
                )
                try:
                    for chunk in chunks:
                        if execution_context is not None and execution_context.cancelled:
                            if hasattr(chunks, "close") and callable(getattr(chunks, "close")):
                                chunks.close()
                            break
                        if chunk.delta:
                            content_parts.append(chunk.delta)
                        if chunk.thinking_delta:
                            thinking_parts.append(chunk.thinking_delta)
                        if chunk.tool_call_delta:
                            tcd = chunk.tool_call_delta
                            idx = tcd.index if tcd.index is not None else 0
                            if idx not in tool_calls_map:
                                tool_calls_map[idx] = {"id": "", "name": "", "args": ""}
                            if tcd.id:
                                tool_calls_map[idx]["id"] = tcd.id
                            if tcd.name:
                                tool_calls_map[idx]["name"] = tcd.name
                            if tcd.arguments_delta:
                                tool_calls_map[idx]["args"] += tcd.arguments_delta
                        if chunk.usage:
                            final_usage = chunk.usage

                        if on_stream_chunk is not None:
                            on_stream_chunk(chunk)
                finally:
                    if hasattr(chunks, "close") and callable(getattr(chunks, "close")):
                        try:
                            chunks.close()
                        except Exception:
                            pass

                assembled_tool_call: ToolCall | None = None
                if tool_calls_map:
                    tc_dict = tool_calls_map[min(tool_calls_map.keys())]
                    raw_args = tc_dict["args"]
                    try:
                        parsed_args = json.loads(raw_args) if raw_args.strip() else {}
                    except ValueError:
                        parsed_args = {}
                    assembled_tool_call = ToolCall(
                        name=tc_dict["name"],
                        arguments=parsed_args if isinstance(parsed_args, dict) else {},
                        call_id=tc_dict["id"] or None,
                    )

                response = ModelResponse(
                    content="".join(content_parts),
                    thinking="".join(thinking_parts),
                    tool_call=assembled_tool_call,
                    usage=final_usage,
                )
            else:
                response = provider.complete(
                    messages=active_context.messages,
                    tools=available_tools,
                    model=model,
                )
        except LimitExceededError:
            raise
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

        if limits is not None:
            u = response.usage
            if u is None:
                if (
                    limits.max_input_tokens is not None
                    or limits.max_output_tokens is not None
                    or limits.max_total_tokens is not None
                ):
                    raise LimitExceededError(
                        "token_limit_accounting_unavailable",
                        "token usage accounting unavailable for limit verification",
                    )
                if limits.max_cost is not None:
                    raise LimitExceededError(
                        "cost_limit_accounting_unavailable",
                        "cost accounting unavailable for limit verification",
                    )
            else:
                if limits.max_input_tokens is not None:
                    if u.input_tokens is None:
                        raise LimitExceededError(
                            "token_limit_accounting_unavailable",
                            "input token accounting unavailable for limit verification",
                        )
                    acc_input_tokens += u.input_tokens
                    if acc_input_tokens > limits.max_input_tokens:
                        raise LimitExceededError(
                            "max_input_tokens_exceeded", "input token limit exceeded"
                        )
                if limits.max_output_tokens is not None:
                    if u.output_tokens is None:
                        raise LimitExceededError(
                            "token_limit_accounting_unavailable",
                            "output token accounting unavailable for limit verification",
                        )
                    acc_output_tokens += u.output_tokens
                    if acc_output_tokens > limits.max_output_tokens:
                        raise LimitExceededError(
                            "max_output_tokens_exceeded", "output token limit exceeded"
                        )
                if limits.max_total_tokens is not None:
                    if u.input_tokens is None or u.output_tokens is None:
                        raise LimitExceededError(
                            "token_limit_accounting_unavailable",
                            "total token accounting unavailable for limit verification",
                        )
                    tot = u.input_tokens + u.output_tokens
                    acc_total_tokens += tot
                    if acc_total_tokens > limits.max_total_tokens:
                        raise LimitExceededError(
                            "max_total_tokens_exceeded", "total token limit exceeded"
                        )
                if limits.max_cost is not None:
                    if u.cost is None:
                        raise LimitExceededError(
                            "cost_limit_accounting_unavailable",
                            "cost accounting unavailable for limit verification",
                        )
                    if limits.currency is not None and u.currency != limits.currency:
                        raise LimitExceededError(
                            "currency_mismatch",
                            f"currency mismatch: expected {limits.currency}, got {u.currency}",
                        )
                    acc_cost += u.cost
                    if acc_cost > limits.max_cost:
                        raise LimitExceededError(
                            "max_cost_exceeded", "cost limit exceeded"
                        )

        if response.tool_call is not None:
            if executor is None:
                return response.tool_call
            tool_calls += 1
            max_allowed = limits.max_tool_calls if limits is not None and limits.max_tool_calls is not None else max_tool_calls
            if tool_calls > max_allowed:
                if limits is not None and limits.max_tool_calls is not None:
                    raise LimitExceededError("max_tool_calls_exceeded", "maximum tool-call limit exceeded")
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

        if execution_context is not None and execution_context.cancelled:
            raise AgentError("task execution cancelled")

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
