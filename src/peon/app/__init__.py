"""Peon application shells, CLI, TUI, and presentation policy."""

from importlib import import_module

_EXPORTS = {
	"DEFAULT_COMMAND_CATALOG": (".commands", "DEFAULT_COMMAND_CATALOG"),
	"CommandError": (".cli", "CommandError"),
	"CommandCatalog": (".commands", "CommandCatalog"),
	"CommandDefinition": (".commands", "CommandDefinition"),
	"CommandInvocation": (".commands", "CommandInvocation"),
	"CommandMatch": (".commands", "CommandMatch"),
	"CodingSession": (".coding_session", "CodingSession"),
	"JsonProviderConfigStore": (".config", "JsonProviderConfigStore"),
	"JsonlTraceSink": (".observability", "JsonlTraceSink"),
	"JsonlSessionStore": (".sessions", "JsonlSessionStore"),
	"MemorySessionStore": (".sessions", "MemorySessionStore"),
	"MessageEvent": (".coding_session", "MessageEvent"),
	"SessionEvent": (".coding_session", "SessionEvent"),
	"ProviderConfig": (".cli", "ProviderConfig"),
	"ProviderConfigStore": (".config", "ProviderConfigStore"),
	"SessionRecord": (".sessions", "SessionRecord"),
	"SessionStore": (".sessions", "SessionStore"),
	"SessionStoreError": (".sessions", "SessionStoreError"),
	"TuiSession": (".tui", "TuiSession"),
	"TurnFinishedEvent": (".coding_session", "TurnFinishedEvent"),
	"TurnResult": (".coding_session", "TurnResult"),
	"TurnStartedEvent": (".coding_session", "TurnStartedEvent"),
	"UiConfig": (".config", "UiConfig"),
	"build_parser": (".cli", "build_parser"),
	"main": (".cli", "main"),
	"run_tui": (".tui", "run_tui"),
}


def __getattr__(name: str) -> object:
	try:
		module_name, attribute_name = _EXPORTS[name]
	except KeyError as error:
		raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from error
	value = getattr(import_module(module_name, __name__), attribute_name)
	globals()[name] = value
	return value

__all__ = [
	"DEFAULT_COMMAND_CATALOG",
	"CommandError",
	"CommandCatalog",
	"CommandDefinition",
	"CommandInvocation",
	"CommandMatch",
	"CodingSession",
	"JsonProviderConfigStore",
	"JsonlTraceSink",
	"JsonlSessionStore",
	"MemorySessionStore",
	"MessageEvent",
	"SessionEvent",
	"ProviderConfig",
	"ProviderConfigStore",
	"SessionRecord",
	"SessionStore",
	"SessionStoreError",
	"TuiSession",
	"TurnFinishedEvent",
	"TurnResult",
	"TurnStartedEvent",
	"UiConfig",
	"build_parser",
	"main",
	"run_tui",
]
