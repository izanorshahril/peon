"""Small provider-neutral extension used in integration examples."""

from collections.abc import Mapping

from .registry import ExtensionRegistry


def register_sample_tools(registry: ExtensionRegistry) -> None:
    """Register the sample tools on an application-owned registry."""
    registry.register_tool(
        name="word_count",
        description="Count the whitespace-separated words in a text value.",
        parameters={
            "type": "object",
            "required": ["text"],
            "properties": {"text": {"type": "string"}},
        },
        handler=_word_count,
    )


def _word_count(arguments: Mapping[str, object]) -> str:
    text = arguments.get("text")
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    return f"word count: {len(text.split())}"