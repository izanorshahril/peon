"""Persistent provider configuration for the interactive application."""

from collections.abc import Mapping, Sequence
import json
import os
from pathlib import Path
from dataclasses import asdict, dataclass, replace
from typing import Literal, Protocol

from peon.agent import ToolDefinition, ToolExecutionContext, ToolExecutor

REASONING_EFFORTS = ("none", "low", "medium", "high")
PROVIDER_REASONING_CAPABILITIES = {
    "openai-compatible": REASONING_EFFORTS,
    "custom": REASONING_EFFORTS,
}


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    name: str
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    copilot_token: str | None = None
    models: tuple[str, ...] = ()
    provider_type: str | None = None
    reasoning_effort_field: str = "reasoningEffort"
    reasoning_effort: str | None = "low"
    temperature_field: str = "temperature"
    temperature: float | None = 1
    max_response_tokens_field: str = "maxResponseTokens"
    max_response_tokens: int | None = 4096
    max_output_tokens_field: str = "maxOutputTokens"
    max_output_tokens: int | None = None
    max_tokens_field: str = "maxTokens"
    max_tokens: int | None = None
    response_format_field: str = "responseFormat"
    response_format: str | None = "text"
    response_content_field: str = "completion"
    response_thinking_field: str = "thinking"
    tool_prompt_role: str = "developer"
    supports_tools: bool | None = None
    supports_stream: bool = False
    supports_chat_completions: bool = True

    def __post_init__(self) -> None:
        if self.supports_tools is None:
            provider_type = self.provider_type or self.name
            object.__setattr__(self, "supports_tools", provider_type != "custom")


def reasoning_effort_choices(config: ProviderConfig) -> tuple[str, ...]:
    provider_type = config.provider_type or config.name
    return PROVIDER_REASONING_CAPABILITIES.get(provider_type, ())


def cycle_reasoning_effort(config: ProviderConfig, direction: int = 1) -> str:
    choices = reasoning_effort_choices(config)
    if not choices:
        raise ValueError("reasoning effort is not supported by this provider")
    current = config.reasoning_effort or "none"
    try:
        index = choices.index(current)
    except ValueError:
        index = -1 if direction > 0 else 0
    return choices[(index + direction) % len(choices)]


@dataclass(frozen=True, slots=True)
class ProviderSettingSpec:
    key: str
    label: str
    field_name: str
    value_kind: Literal["text", "secret", "integer", "temperature", "choice", "toggle"]
    choices: tuple[str, ...] = ()


PROFILE_SETTING_SPECS = (
    ProviderSettingSpec("name", "Name", "name", "text"),
)
CONFIG_SETTING_SPECS = (
    ProviderSettingSpec("base-url", "Base URL", "base_url", "text"),
    ProviderSettingSpec("api-key", "API key", "api_key", "secret"),
    ProviderSettingSpec(
        "max-completion-tokens",
        "Max completion tokens",
        "max_response_tokens",
        "integer",
    ),
    ProviderSettingSpec(
        "max-output-tokens", "Max output tokens", "max_output_tokens", "integer"
    ),
    ProviderSettingSpec("max-tokens", "Max tokens", "max_tokens", "integer"),
    ProviderSettingSpec(
        "reasoning",
        "Reasoning",
        "reasoning_effort",
        "choice",
        ("none", "low", "medium", "high"),
    ),
    ProviderSettingSpec("supports-tools", "Supports tools", "supports_tools", "toggle"),
    ProviderSettingSpec("supports-stream", "Supports stream", "supports_stream", "toggle"),
    ProviderSettingSpec(
        "supports-chat-completions",
        "Supports chat completions",
        "supports_chat_completions",
        "toggle",
    ),
    ProviderSettingSpec(
        "tool-prompt-role",
        "Tool prompt role",
        "tool_prompt_role",
        "choice",
        ("developer", "system"),
    ),
    ProviderSettingSpec("temperature", "Temperature", "temperature", "temperature"),
)


@dataclass(frozen=True, slots=True)
class SavedModel:
    config: ProviderConfig
    model: str

    @property
    def label(self) -> str:
        return f"{self.model} [{self.config.name}]"


def saved_model_choices(
    configs: Sequence[ProviderConfig],
) -> tuple[SavedModel, ...]:
    return tuple(
        SavedModel(config=config, model=model)
        for config in configs
        for model in config.models
    )


def select_saved_model(
    selection: str,
    choices: tuple[SavedModel, ...],
) -> SavedModel:
    if selection.isdigit():
        index = int(selection) - 1
        if 0 <= index < len(choices):
            return choices[index]
    matches = tuple(choice for choice in choices if choice.model == selection)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError("select model by number when model IDs repeat")
    raise ValueError("select a model by number or exact model ID")


DEFAULT_ENABLED_TOOLS = ("read", "write", "edit", "bash")


@dataclass(frozen=True, slots=True)
class UiConfig:
    user_top_blank_lines: int = 1
    user_bottom_blank_lines: int = 1
    message_left_padding: int = 1
    background_color: str = "#121212"
    chat_area_color: str = "#121212"
    user_message_color: str = "#c4c4c4"
    user_message_background: str = "#3a3a44"
    assistant_message_color: str = "#e0e0e0"
    tool_message_background: str = "#283228"
    tool_output_color: str = "#808080"
    command_selected_color: str = "#000000"
    text_format: str = "normal"
    system_text_format: str = "normal"
    hide_thinking: bool = False
    render_tool_markdown: bool = False
    session_list_delimiter: bool = True
    reasoning_shortcut: str = "shift+tab"
    thinking_shortcut: str = "ctrl+t"
    tools_shortcut: str = "ctrl+o"
    enabled_tools: tuple[str, ...] = DEFAULT_ENABLED_TOOLS


UI_SETTING_SPECS = (
    ("user-top-spacing", "User top spacing", "user_top_blank_lines"),
    ("user-bottom-spacing", "User bottom spacing", "user_bottom_blank_lines"),
    ("message-left-padding", "Message left padding", "message_left_padding"),
    ("background-color", "Background color", "background_color"),
    ("chat-area-color", "Chat area color", "chat_area_color"),
    ("user-message-color", "User message color", "user_message_color"),
    (
        "user-message-background",
        "User message background",
        "user_message_background",
    ),
    (
        "assistant-message-color",
        "Assistant message color",
        "assistant_message_color",
    ),
    (
        "tool-message-background",
        "Tool message background",
        "tool_message_background",
    ),
    ("tool-output-color", "Tool output color", "tool_output_color"),
    (
        "command-selected-color",
        "Command selected color",
        "command_selected_color",
    ),
    ("text-format", "Text format", "text_format"),
    ("system-text-format", "System text format", "system_text_format"),
)

GENERAL_SETTING_SPECS = (
    ("hide-thinking", "Hide thinking blocks", "hide_thinking"),
    (
        "render-tool-markdown",
        "Render tool output as Markdown",
        "render_tool_markdown",
    ),
    (
        "session-list-delimiter",
        "Session list dot delimiters",
        "session_list_delimiter",
    ),
    ("reserved-auto-compaction", "Auto-compaction", None),
)

SHORTCUT_SETTING_SPECS = (
    ("reasoning", "Cycle reasoning effort", "reasoning_shortcut"),
    ("thinking", "Show or hide thinking", "thinking_shortcut"),
    ("tools", "Expand or collapse tools", "tools_shortcut"),
)


def update_ui_setting(config: UiConfig, setting: str, value: str) -> UiConfig:
    field_name = next(
        (
            field
            for key, _label, field in UI_SETTING_SPECS
            if key == setting
        ),
        None,
    )
    if field_name is None:
        raise ValueError(f"unknown UI setting '{setting}'")
    if field_name in {
        "user_top_blank_lines",
        "user_bottom_blank_lines",
        "message_left_padding",
    }:
        try:
            parsed_value = int(value)
        except ValueError as error:
            raise ValueError("spacing and padding must be integers") from error
        if not 0 <= parsed_value <= 8:
            raise ValueError("spacing and padding must be between 0 and 8")
        if field_name == "user_top_blank_lines":
            return replace(config, user_top_blank_lines=parsed_value)
        if field_name == "user_bottom_blank_lines":
            return replace(config, user_bottom_blank_lines=parsed_value)
        return replace(config, message_left_padding=parsed_value)
    if field_name in {"text_format", "system_text_format"}:
        lowered_value = value.lower()
        if lowered_value not in {"normal", "bold", "italic"}:
            raise ValueError("text format must be normal, bold, or italic")
        if field_name == "text_format":
            return replace(config, text_format=lowered_value)
        return replace(config, system_text_format=lowered_value)
    if not value.startswith("#") or len(value) not in {4, 7}:
        raise ValueError("colors must use #RGB or #RRGGBB")
    try:
        int(value[1:], 16)
    except ValueError as error:
        raise ValueError("colors must use hexadecimal digits") from error
    if field_name == "background_color":
        return replace(config, background_color=value)
    if field_name == "chat_area_color":
        return replace(config, chat_area_color=value)
    if field_name == "user_message_color":
        return replace(config, user_message_color=value)
    if field_name == "user_message_background":
        return replace(config, user_message_background=value)
    if field_name == "assistant_message_color":
        return replace(config, assistant_message_color=value)
    if field_name == "tool_message_background":
        return replace(config, tool_message_background=value)
    if field_name == "tool_output_color":
        return replace(config, tool_output_color=value)
    return replace(config, command_selected_color=value)


def update_general_setting(config: UiConfig, setting: str, value: str) -> UiConfig:
    field_name = next(
        (
            field
            for key, _label, field in GENERAL_SETTING_SPECS
            if key == setting
        ),
        None,
    )
    if field_name is None:
        raise ValueError(f"setting '{setting}' is reserved")
    lowered_value = value.lower()
    if lowered_value not in {"true", "false"}:
        raise ValueError("general setting must be true or false")
    if field_name == "hide_thinking":
        return replace(config, hide_thinking=lowered_value == "true")
    if field_name == "render_tool_markdown":
        return replace(config, render_tool_markdown=lowered_value == "true")
    return replace(config, session_list_delimiter=lowered_value == "true")


def update_shortcut_setting(config: UiConfig, setting: str, value: str) -> UiConfig:
    field_name = next(
        (
            field
            for key, _label, field in SHORTCUT_SETTING_SPECS
            if key == setting
        ),
        None,
    )
    if field_name is None:
        raise ValueError(f"unknown shortcut setting '{setting}'")
    normalized_value = value.strip().lower()
    if not normalized_value or any(character.isspace() for character in normalized_value):
        raise ValueError("shortcut cannot be blank or contain spaces")
    if any(
        other_field != field_name
        and normalized_value == str(getattr(config, other_field)).casefold()
        for _key, _label, other_field in SHORTCUT_SETTING_SPECS
    ):
        raise ValueError("shortcut is already assigned")
    if field_name == "reasoning_shortcut":
        return replace(config, reasoning_shortcut=normalized_value)
    if field_name == "thinking_shortcut":
        return replace(config, thinking_shortcut=normalized_value)
    return replace(config, tools_shortcut=normalized_value)


CAPABILITY_PROFILES: dict[str, tuple[str, ...]] = {
    "none": (),
    "read-only": ("read", "list", "grep", "find"),
    "coding": ("read", "write", "edit", "bash"),
}


def active_capability_profile(config: UiConfig) -> str:
    """Return active capability profile name based on enabled_tools."""
    enabled_set = set(config.enabled_tools)
    for profile_name, tools in CAPABILITY_PROFILES.items():
        if enabled_set == set(tools):
            return profile_name
    return "custom"


def set_capability_profile(config: UiConfig, profile_name: str) -> UiConfig:
    """Return updated UiConfig with specified capability profile."""
    normalized = profile_name.strip().lower()
    if normalized in CAPABILITY_PROFILES:
        tools = CAPABILITY_PROFILES[normalized]
        return replace(config, enabled_tools=tools)
    if normalized == "custom":
        return config
    raise ValueError(
        f"Unknown capability profile '{profile_name}'. Valid profiles: none, read-only, coding, custom."
    )


def enabled_tool_names(config: UiConfig) -> tuple[str, ...]:
    """Return the configured model-facing tools in stable order."""
    return config.enabled_tools


def update_tool_setting(config: UiConfig, tool_name: str, value: str) -> UiConfig:
    normalized_name = tool_name.strip()
    if not normalized_name:
        raise ValueError("tool name cannot be blank")
    lowered_value = value.strip().lower()
    if lowered_value not in {"true", "false"}:
        raise ValueError("tool availability must be true or false")
    enabled = list(config.enabled_tools)
    if lowered_value == "true" and normalized_name not in enabled:
        enabled.append(normalized_name)
    elif lowered_value == "false":
        enabled = [name for name in enabled if name != normalized_name]
    return replace(config, enabled_tools=tuple(enabled))


def filter_enabled_tools(
    config: UiConfig,
    tools: Sequence[ToolDefinition],
) -> tuple[ToolDefinition, ...]:
    """Return registered definitions allowed in provider requests."""
    enabled = set(enabled_tool_names(config))
    return tuple(tool for tool in tools if tool.name in enabled)


class FilteredToolExecutor:
    """Expose only configured tool definitions and invocations."""

    def __init__(self, executor: ToolExecutor, config: UiConfig) -> None:
        self._executor = executor
        self._tools = filter_enabled_tools(config, executor.tools)
        self._enabled_names = {tool.name for tool in self._tools}

    @property
    def tools(self) -> tuple[ToolDefinition, ...]:
        return self._tools

    def invoke(self, name: str, arguments: Mapping[str, object]) -> str:
        if name not in self._enabled_names:
            raise ValueError(f"tool '{name}' is disabled")
        return self._executor.invoke(name, arguments)

    def invoke_with_context(
        self,
        name: str,
        arguments: Mapping[str, object],
        context: ToolExecutionContext,
    ) -> str:
        if name not in self._enabled_names:
            raise ValueError(f"tool '{name}' is disabled")
        contextual_invoke = getattr(self._executor, "invoke_with_context", None)
        if callable(contextual_invoke):
            return contextual_invoke(name, arguments, context)
        return self._executor.invoke(name, arguments)


def filter_tool_executor(
    config: UiConfig,
    executor: ToolExecutor,
) -> FilteredToolExecutor:
    return FilteredToolExecutor(executor, config)


class ProviderConfigStore(Protocol):
    def load(self) -> ProviderConfig | None:
        """Load the saved provider configuration, if one exists."""

    def load_all(self) -> tuple[ProviderConfig, ...]:
        """Load all saved provider configurations in display order."""

    def save(self, config: ProviderConfig) -> None:
        """Persist one provider configuration."""

    def delete(self, config: ProviderConfig) -> None:
        """Remove one saved provider configuration, if it exists."""

    def load_ui(self) -> UiConfig:
        """Load persisted UI preferences."""

    def save_ui(self, config: UiConfig) -> None:
        """Persist UI preferences."""

    def update(self, previous: ProviderConfig, config: ProviderConfig) -> None:
        """Replace a provider profile, including identity fields."""


class JsonProviderConfigStore:
    """Store the interactive provider configuration in a local JSON file."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_provider_config_path()

    def load(self) -> ProviderConfig | None:
        configs = self.load_all()
        if not configs:
            return None
        try:
            raw_config = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return configs[0]
        if isinstance(raw_config, Mapping):
            active = raw_config.get("active")
            if isinstance(active, str):
                for config in configs:
                    if provider_id(config) == active:
                        return config
        return configs[0]

    def load_all(self) -> tuple[ProviderConfig, ...]:
        try:
            raw_config = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ()
        if not isinstance(raw_config, Mapping):
            return ()

        raw_providers = raw_config.get("providers")
        if isinstance(raw_providers, list):
            configs: list[ProviderConfig] = []
            for raw_provider in raw_providers:
                config = _parse_provider_config(raw_provider)
                if config is None:
                    return ()
                configs.append(config)
            return tuple(configs)

        config = _parse_provider_config(raw_config)
        return (config,) if config is not None else ()

    def save(self, config: ProviderConfig) -> None:
        configs = list(self.load_all())
        config_key = provider_id(config)
        for index, existing in enumerate(configs):
            if provider_id(existing) == config_key:
                configs[index] = config
                break
        else:
            configs.append(config)
        self._write(configs, active=config_key)

    def update(self, previous: ProviderConfig, config: ProviderConfig) -> None:
        previous_key = provider_id(previous)
        configs = list(self.load_all())
        for index, existing in enumerate(configs):
            if provider_id(existing) == previous_key:
                configs[index] = config
                break
        else:
            configs.append(config)
        self._write(configs, active=provider_id(config))

    def load_ui(self) -> UiConfig:
        try:
            raw_config = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return UiConfig()
        if not isinstance(raw_config, Mapping):
            return UiConfig()
        raw_ui = raw_config.get("ui")
        if not isinstance(raw_ui, Mapping):
            return UiConfig()
        defaults = UiConfig()
        values: dict[str, object] = {}
        for field_name in asdict(defaults):
            value = raw_ui.get(field_name, getattr(defaults, field_name))
            default = getattr(defaults, field_name)
            if field_name == "enabled_tools" and isinstance(value, list):
                if all(isinstance(tool_name, str) for tool_name in value):
                    value = tuple(value)
            if type(value) is not type(default):
                return defaults
            values[field_name] = value
        return UiConfig(**values)  # type: ignore[arg-type]

    def save_ui(self, config: UiConfig) -> None:
        providers = list(self.load_all())
        active = self.load()
        self._write(
            providers,
            active=provider_id(active) if active is not None else "",
            ui=config,
        )

    def delete(self, config: ProviderConfig) -> None:
        active_config = self.load()
        configs = [
            existing
            for existing in self.load_all()
            if provider_id(existing) != provider_id(config)
        ]
        if configs:
            active = (
                provider_id(active_config)
                if active_config is not None
                and provider_id(active_config) != provider_id(config)
                else provider_id(configs[0])
            )
            self._write(configs, active=active)
        else:
            ui = self.load_ui()
            if ui == UiConfig():
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
            else:
                self._write([], active="", ui=ui)

    def _write(
        self,
        configs: list[ProviderConfig],
        *,
        active: str,
        ui: UiConfig | None = None,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(f".{self.path.name}.tmp")
        payload = {
            "active": active,
            "providers": [_serialize_provider_config(config) for config in configs],
            "ui": asdict(ui or self.load_ui()),
        }
        try:
            temporary_path.write_text(
                json.dumps(payload, indent=2) + "\n",
                encoding="utf-8",
            )
            try:
                os.chmod(temporary_path, 0o600)
            except OSError:
                pass
            os.replace(temporary_path, self.path)
        except OSError:
            try:
                temporary_path.unlink()
            except OSError:
                pass
            raise


def _parse_provider_config(raw_config: object) -> ProviderConfig | None:
    if not isinstance(raw_config, Mapping):
        return None

    name = raw_config.get("name")
    if not isinstance(name, str) or not name.strip():
        return None

    raw_models = raw_config.get("models", [])
    if not isinstance(raw_models, list):
        return None
    models: list[str] = []
    for model in raw_models:
        if not isinstance(model, str) or not model.strip():
            return None
        models.append(model)

    optional_values: dict[str, str | None] = {}
    for field_name in (
        "provider_type",
        "model",
        "base_url",
        "api_key",
        "copilot_token",
        "reasoning_effort_field",
        "reasoning_effort",
        "temperature_field",
        "max_response_tokens_field",
        "max_output_tokens_field",
        "max_tokens_field",
        "response_format_field",
        "response_format",
        "response_content_field",
        "response_thinking_field",
        "tool_prompt_role",
    ):
        value = raw_config.get(field_name)
        if value is not None and not isinstance(value, str):
            return None
        optional_values[field_name] = value
    tool_prompt_role = optional_values.get("tool_prompt_role")
    if tool_prompt_role is not None and tool_prompt_role not in {"system", "developer"}:
        return None

    numeric_values: dict[str, int | float | None] = {}
    for field_name in (
        "temperature",
        "max_response_tokens",
        "max_output_tokens",
        "max_tokens",
    ):
        value = raw_config.get(field_name)
        if value is not None and (
            not isinstance(value, (int, float)) or isinstance(value, bool)
        ):
            return None
        numeric_values[field_name] = value

    boolean_values: dict[str, bool] = {}
    provider_type = optional_values["provider_type"] or name
    for field_name, default in (
        ("supports_tools", provider_type != "custom"),
        ("supports_stream", False),
        ("supports_chat_completions", True),
    ):
        value = raw_config.get(field_name, default)
        if not isinstance(value, bool):
            return None
        boolean_values[field_name] = value

    reasoning_effort = optional_values.pop("reasoning_effort")
    response_format = optional_values.pop("response_format")

    return ProviderConfig(
        name=name,
        provider_type=optional_values.pop("provider_type"),
        model=optional_values.pop("model"),
        models=tuple(models),
        base_url=optional_values.pop("base_url"),
        api_key=optional_values.pop("api_key"),
        copilot_token=optional_values.pop("copilot_token"),
        reasoning_effort_field=optional_values.pop(
            "reasoning_effort_field"
        ) or "reasoningEffort",
        reasoning_effort=(
            reasoning_effort if "reasoning_effort" in raw_config else "low"
        ),
        temperature_field=optional_values.pop("temperature_field") or "temperature",
        max_response_tokens_field=optional_values.pop(
            "max_response_tokens_field"
        ) or "maxResponseTokens",
        max_output_tokens_field=optional_values.pop("max_output_tokens_field")
        or "maxOutputTokens",
        max_tokens_field=optional_values.pop("max_tokens_field") or "maxTokens",
        response_format_field=optional_values.pop(
            "response_format_field"
        ) or "responseFormat",
        temperature=numeric_values["temperature"]
        if numeric_values["temperature"] is not None
        else (None if "temperature" in raw_config else 1),
        max_response_tokens=int(numeric_values["max_response_tokens"])
        if numeric_values["max_response_tokens"] is not None
        else (None if "max_response_tokens" in raw_config else 4096),
        max_output_tokens=int(numeric_values["max_output_tokens"])
        if numeric_values["max_output_tokens"] is not None
        else None,
        max_tokens=int(numeric_values["max_tokens"])
        if numeric_values["max_tokens"] is not None
        else None,
        response_format=(
            response_format if "response_format" in raw_config else "text"
        ),
        response_content_field=optional_values.pop("response_content_field")
        or "completion",
        response_thinking_field=optional_values.pop("response_thinking_field")
        or "thinking",
        tool_prompt_role=tool_prompt_role or "developer",
        supports_tools=boolean_values["supports_tools"],
        supports_stream=boolean_values["supports_stream"],
        supports_chat_completions=boolean_values["supports_chat_completions"],
    )


def _serialize_provider_config(config: ProviderConfig) -> dict[str, object]:
    return {
        "name": config.name,
        "provider_type": config.provider_type,
        "model": config.model,
        "models": list(config.models),
        "base_url": config.base_url,
        "api_key": config.api_key,
        "copilot_token": config.copilot_token,
        "reasoning_effort_field": config.reasoning_effort_field,
        "reasoning_effort": config.reasoning_effort,
        "temperature_field": config.temperature_field,
        "temperature": config.temperature,
        "max_response_tokens_field": config.max_response_tokens_field,
        "max_response_tokens": config.max_response_tokens,
        "max_output_tokens_field": config.max_output_tokens_field,
        "max_output_tokens": config.max_output_tokens,
        "max_tokens_field": config.max_tokens_field,
        "max_tokens": config.max_tokens,
        "response_format_field": config.response_format_field,
        "response_format": config.response_format,
        "response_content_field": config.response_content_field,
        "response_thinking_field": config.response_thinking_field,
        "tool_prompt_role": config.tool_prompt_role,
        "supports_tools": config.supports_tools,
        "supports_stream": config.supports_stream,
        "supports_chat_completions": config.supports_chat_completions,
    }


def provider_id(config: ProviderConfig) -> str:
    return f"{config.name}\x1f{config.base_url or ''}"


def load_ui_config(store: ProviderConfigStore) -> UiConfig:
    loader = getattr(store, "load_ui", None)
    return loader() if callable(loader) else UiConfig()


def save_ui_config(store: ProviderConfigStore, config: UiConfig) -> None:
    saver = getattr(store, "save_ui", None)
    if callable(saver):
        saver(config)


def update_saved_provider(
    store: ProviderConfigStore,
    previous: ProviderConfig,
    config: ProviderConfig,
) -> None:
    updater = getattr(store, "update", None)
    if callable(updater):
        updater(previous, config)
        return
    if provider_id(previous) != provider_id(config):
        store.delete(previous)
    store.save(config)


def default_provider_config_path() -> Path:
    override = os.environ.get("PEON_CONFIG_FILE")
    if override:
        return Path(override)

    if os.name == "nt":
        config_root = os.environ.get("APPDATA")
    else:
        config_root = os.environ.get("XDG_CONFIG_HOME")
    root = Path(config_root) if config_root else Path.home() / ".config"
    return root / "peon" / "provider.json"
