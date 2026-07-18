"""Peon application shells, CLI, TUI, and presentation policy."""

from .cli import CommandError, ProviderConfig, build_parser, main
from .commands import (
	DEFAULT_COMMAND_CATALOG,
	CommandCatalog,
	CommandDefinition,
	CommandInvocation,
	CommandMatch,
)
from .config import JsonProviderConfigStore, ProviderConfigStore, UiConfig
from .tui import TuiSession, run_tui

__all__ = [
	"DEFAULT_COMMAND_CATALOG",
	"CommandError",
	"CommandCatalog",
	"CommandDefinition",
	"CommandInvocation",
	"CommandMatch",
	"JsonProviderConfigStore",
	"ProviderConfig",
	"ProviderConfigStore",
	"TuiSession",
	"UiConfig",
	"build_parser",
	"main",
	"run_tui",
]
