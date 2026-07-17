"""Persistent provider configuration for the interactive application."""

from collections.abc import Mapping
import json
import os
from pathlib import Path
from typing import Protocol

from .cli import ProviderConfig


class ProviderConfigStore(Protocol):
    def load(self) -> ProviderConfig | None:
        """Load the saved provider configuration, if one exists."""

    def load_all(self) -> tuple[ProviderConfig, ...]:
        """Load all saved provider configurations in display order."""

    def save(self, config: ProviderConfig) -> None:
        """Persist one provider configuration."""

    def delete(self, config: ProviderConfig) -> None:
        """Remove one saved provider configuration, if it exists."""


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
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass

    def _write(
        self,
        configs: list[ProviderConfig],
        *,
        active: str,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(f".{self.path.name}.tmp")
        payload = {
            "active": active,
            "providers": [_serialize_provider_config(config) for config in configs],
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
    for field_name in ("model", "base_url", "api_key", "copilot_token"):
        value = raw_config.get(field_name)
        if value is not None and not isinstance(value, str):
            return None
        optional_values[field_name] = value

    return ProviderConfig(name=name, models=tuple(models), **optional_values)


def _serialize_provider_config(config: ProviderConfig) -> dict[str, object]:
    return {
        "name": config.name,
        "model": config.model,
        "models": list(config.models),
        "base_url": config.base_url,
        "api_key": config.api_key,
        "copilot_token": config.copilot_token,
    }


def provider_id(config: ProviderConfig) -> str:
    return f"{config.name}\x1f{config.base_url or ''}"


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