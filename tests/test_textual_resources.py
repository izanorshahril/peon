import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from peon.agent import AgentMessage, ModelResponse, ToolDefinition
from peon.app import ProviderConfig, UiConfig
from peon.app.resources import ResourceLoader
from peon.app.sessions import MemorySessionStore
from peon.app.textual_tui import TextualPeonApp
from peon.extensions import ExtensionRegistry


@dataclass
class FakeProvider:
    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        del messages, tools, model
        return ModelResponse(content="ok")


@dataclass
class MemoryConfigStore:
    configuration: ProviderConfig
    ui_configuration: UiConfig = field(default_factory=UiConfig)

    def load(self) -> ProviderConfig:
        return self.configuration

    def load_all(self) -> tuple[ProviderConfig, ...]:
        return (self.configuration,)

    def save(self, config: ProviderConfig) -> None:
        self.configuration = config

    def delete(self, config: ProviderConfig) -> None:
        del config

    def load_ui(self) -> UiConfig:
        return self.ui_configuration

    def save_ui(self, config: UiConfig) -> None:
        self.ui_configuration = config


def _resources(tmp_path: Path):
    (tmp_path / "SYSTEM.md").write_text("current project rules", encoding="utf-8")
    return ResourceLoader(
        tmp_path,
        global_root=tmp_path / "missing-global",
    ).load()


def _config() -> ProviderConfig:
    return ProviderConfig(
        name="openai-compatible",
        model="first-model",
        base_url="https://example.test/v1",
    )


def test_textual_startup_and_new_reapply_resource_prompt(tmp_path: Path) -> None:
    async def exercise() -> None:
        resources = _resources(tmp_path)
        store = MemorySessionStore()
        app = TextualPeonApp(
            provider_factory=lambda _config: FakeProvider(),
            config_store=MemoryConfigStore(_config()),
            registry=ExtensionRegistry(),
            session_store=store,
            resources=resources,
        )

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.context.messages == [
                AgentMessage(role="system", content="current project rules"),
            ]
            app._handle_command("/new")
            assert app.context.messages == [
                AgentMessage(role="system", content="current project rules"),
            ]
            assert app.persisted_message_count == 1
            assert store.load(app.session_id).messages == ()

    asyncio.run(exercise())


def test_textual_resume_reapplies_resource_prompt(tmp_path: Path) -> None:
    async def exercise() -> None:
        resources = _resources(tmp_path)
        store = MemorySessionStore()
        saved = store.create(name="release")
        store.append(saved.session_id, AgentMessage(role="user", content="old task"))
        app = TextualPeonApp(
            provider_factory=lambda _config: FakeProvider(),
            config_store=MemoryConfigStore(_config()),
            registry=ExtensionRegistry(),
            session_store=store,
            resources=resources,
        )

        async with app.run_test() as pilot:
            await pilot.pause()
            app._handle_command("/resume release")
            assert app.context.messages == [
                AgentMessage(role="system", content="current project rules"),
                AgentMessage(role="user", content="old task"),
            ]
            assert app.persisted_message_count == 2

    asyncio.run(exercise())


def test_textual_fork_does_not_persist_resource_prompt(tmp_path: Path) -> None:
    async def exercise() -> None:
        resources = _resources(tmp_path)
        store = MemorySessionStore()
        app = TextualPeonApp(
            provider_factory=lambda _config: FakeProvider(),
            config_store=MemoryConfigStore(_config()),
            registry=ExtensionRegistry(),
            session_store=store,
            resources=resources,
        )

        async with app.run_test() as pilot:
            await pilot.pause()
            app._write("old task", role="user")
            app.context.messages.append(AgentMessage(role="user", content="old task"))
            app._fork_current_session("branch")
            child = store.load(app.session_id)
            assert all(message.role != "system" for message in child.messages)
            assert app.context.messages[0] == AgentMessage(
                role="system",
                content="current project rules",
            )

    asyncio.run(exercise())
