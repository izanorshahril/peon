"""Shared slash-command vocabulary, search, and resolution."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Literal

CommandAvailability = Literal[
    "available",
    "reserved",
    "hidden-compatibility",
]
ArgumentPolicy = Literal["none", "optional", "required"]
MatchKind = Literal[
    "canonical-exact",
    "canonical-prefix",
    "candidate-exact",
    "candidate-prefix",
    "token-match",
    "description-match",
    "catalog-order",
]


@dataclass(frozen=True, slots=True)
class CommandDefinition:
    """Metadata for one command purpose and all of its vocabulary."""

    id: str
    name: str
    description: str
    candidate_names: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    search_terms: tuple[str, ...] = ()
    availability: CommandAvailability = "available"
    argument_policy: ArgumentPolicy = "optional"
    order: int = 0
    setting_key: str | None = None


@dataclass(frozen=True, slots=True)
class CommandMatch:
    """A command found by catalog search, including its ranking reason."""

    command: CommandDefinition
    score: int
    match_kind: MatchKind

    @property
    def is_reserved(self) -> bool:
        return self.command.availability == "reserved"


@dataclass(frozen=True, slots=True)
class CommandInvocation:
    """A resolved command ID and the argument text following its name."""

    command: CommandDefinition
    argument: str
    is_direct: bool = True


def _normalize(value: str) -> str:
    without_slash = value.strip().lstrip("/")
    return re.sub(r"[^a-z0-9]+", " ", without_slash.casefold()).strip()


def _tokens(value: str) -> tuple[str, ...]:
    normalized = _normalize(value)
    return tuple(normalized.split()) if normalized else ()


class CommandCatalog:
    """Search and resolve a stable set of slash-command definitions."""

    def __init__(self, commands: Iterable[CommandDefinition]) -> None:
        ordered = sorted(commands, key=lambda command: command.order)
        self._commands = tuple(
            replace(command, order=index)
            for index, command in enumerate(ordered)
        )

    @property
    def commands(self) -> tuple[CommandDefinition, ...]:
        return self._commands

    def search(
        self,
        query: str,
        *,
        include_hidden: bool = False,
    ) -> tuple[CommandMatch, ...]:
        """Return visible commands ordered by match quality, then catalog order."""
        normalized_query = _normalize(query)
        query_tokens = tuple(normalized_query.split()) if normalized_query else ()
        matches: list[CommandMatch] = []
        for command in self._commands:
            if (
                command.availability == "hidden-compatibility"
                and not include_hidden
            ):
                continue
            match = self._match(command, normalized_query, query_tokens)
            if match is not None:
                matches.append(match)
        if not normalized_query:
            return tuple(
                CommandMatch(command, 6, "catalog-order")
                for command in self._commands
                if include_hidden or command.availability != "hidden-compatibility"
            )
        return tuple(sorted(matches, key=lambda match: (match.score, match.command.order)))

    def resolve(self, text: str) -> CommandInvocation | None:
        """Resolve a slash command, preserving arguments only after direct name resolution."""
        stripped = text.strip()
        if not stripped.startswith("/"):
            return None
        parts = stripped.split(maxsplit=1)
        name = parts[0]
        separator = len(parts) == 2
        argument = parts[1] if separator else ""
        normalized_name = _normalize(name)
        if not normalized_name:
            return None

        exact = self._direct_matches(normalized_name)
        if exact:
            command = exact[0]
            parsed_argument = argument.strip() if separator else ""
            if command.argument_policy == "none" and parsed_argument:
                return None
            if command.argument_policy == "required" and not parsed_argument:
                return None
            return CommandInvocation(command, parsed_argument)

        if separator:
            return None
        prefix_matches = [
            command
            for command in self._commands
            if self._is_prefix_of_direct_name(normalized_name, command)
        ]
        if not prefix_matches:
            return None
        return CommandInvocation(prefix_matches[0], "", is_direct=False)

    def help_text(self) -> str:
        """Render the public command inventory for either terminal shell."""
        available = [
            command
            for command in self._commands
            if command.availability == "available"
        ]
        reserved = [
            command
            for command in self._commands
            if command.availability == "reserved"
        ]
        sections = [
            self._help_section("Available commands", available),
            self._help_section("Reserved commands", reserved),
        ]
        return "\n\n".join(sections)

    @staticmethod
    def _help_section(
        title: str,
        commands: Iterable[CommandDefinition],
    ) -> str:
        lines = []
        for command in commands:
            candidate_hint = (
                f" (also: {', '.join(command.candidate_names)})"
                if command.candidate_names
                else ""
            )
            lines.append(
                f"{command.name:<11}{command.description}{candidate_hint}"
            )
        return "\n".join((f"{title}:", *lines))

    def _direct_matches(self, normalized_name: str) -> tuple[CommandDefinition, ...]:
        return tuple(
            command
            for command in self._commands
            if normalized_name == _normalize(command.name)
            or any(normalized_name == _normalize(alias) for alias in command.aliases)
        )

    @staticmethod
    def _is_prefix_of_direct_name(
        normalized_name: str,
        command: CommandDefinition,
    ) -> bool:
        return normalized_name in {
            _normalize(command.name),
            *(_normalize(alias) for alias in command.aliases),
        } or any(
            _normalize(name).startswith(normalized_name)
            for name in (command.name, *command.aliases)
        )

    @staticmethod
    def _match(
        command: CommandDefinition,
        normalized_query: str,
        query_tokens: tuple[str, ...],
    ) -> CommandMatch | None:
        canonical = _normalize(command.name)
        candidates = tuple(
            _normalize(name)
            for name in (*command.candidate_names, *command.aliases)
        )
        searchable = _tokens(
            " ".join(
                (
                    command.description,
                    *command.candidate_names,
                    *command.aliases,
                    *command.search_terms,
                )
            )
        )
        if not normalized_query:
            return CommandMatch(command, 6, "catalog-order")
        if normalized_query == canonical:
            return CommandMatch(command, 0, "canonical-exact")
        if " " not in normalized_query and canonical.startswith(normalized_query):
            return CommandMatch(command, 1, "canonical-prefix")
        if normalized_query in candidates:
            return CommandMatch(command, 2, "candidate-exact")
        if " " not in normalized_query and any(
            candidate.startswith(normalized_query) for candidate in candidates
        ):
            return CommandMatch(command, 3, "candidate-prefix")
        if query_tokens and all(token in searchable for token in query_tokens):
            return CommandMatch(command, 4, "token-match")
        if query_tokens and any(token in searchable for token in query_tokens):
            return CommandMatch(command, 5, "description-match")
        return None


def _command(
    id: str,
    name: str,
    description: str,
    *,
    candidate_names: tuple[str, ...] = (),
    aliases: tuple[str, ...] = (),
    search_terms: tuple[str, ...] = (),
    availability: CommandAvailability = "available",
    argument_policy: ArgumentPolicy = "optional",
    setting_key: str | None = None,
) -> CommandDefinition:
    return CommandDefinition(
        id=id,
        name=name,
        description=description,
        candidate_names=candidate_names,
        aliases=aliases,
        search_terms=search_terms,
        availability=availability,
        argument_policy=argument_policy,
        order=len(_COMMAND_DEFINITIONS),
        setting_key=setting_key,
    )


_COMMAND_DEFINITIONS: list[CommandDefinition] = []
_COMMAND_DEFINITIONS.extend(
    (
        _command(
            "help",
            "/help",
            "show available commands",
            candidate_names=("commands",),
            search_terms=("discover commands",),
            argument_policy="none",
        ),
        _command(
            "new",
            "/new",
            "start a clean conversation",
            candidate_names=("reset",),
            aliases=("/clear", "/reset"),
            search_terms=("new session", "start over"),
            argument_policy="none",
        ),
        _command(
            "model",
            "/model",
            "switch the active model",
            aliases=("/models",),
            search_terms=("switch model", "select model", "saved models"),
        ),
        _command(
            "provider",
            "/provider",
            "configure a provider",
            candidate_names=("connect", "login"),
        ),
        _command(
            "settings",
            "/settings",
            "configure UI and saved providers",
            candidate_names=("config",),
            search_terms=("configuration", "preferences"),
        ),
        _command(
            "reasoning",
            "/reasoning",
            "change active model reasoning effort",
            candidate_names=("effort", "thinking"),
            search_terms=("reasoning level", "thinking", "thinking budget"),
            setting_key="reasoning",
        ),
        _command(
            "tools",
            "/tools",
            "list registered tools",
            search_terms=("functions", "capabilities", "tool list"),
        ),
        _command(
            "skills",
            "/skills",
            "list registered skills",
            search_terms=("skill list", "capabilities"),
        ),
        _command(
            "logout",
            "/logout",
            "remove one saved provider",
            candidate_names=("disconnect",),
            search_terms=("sign out",),
        ),
        _command(
            "quit",
            "/quit",
            "exit Peon",
            aliases=("/exit", "/close", "/q"),
            argument_policy="none",
        ),
        _command(
            "session",
            "/session",
            "list or resume conversations",
            candidate_names=("sessions", "resume", "continue"),
            search_terms=("history", "resume", "continue"),
        ),
        _command(
            "compact",
            "/compact",
            "compact conversation context",
            candidate_names=("summarize",),
            availability="reserved",
            search_terms=("summarize context",),
        ),
        _command(
            "export",
            "/export",
            "export the current conversation",
            candidate_names=("save",),
            availability="reserved",
        ),
        _command(
            "share",
            "/share",
            "share the current conversation",
            candidate_names=("publish",),
            availability="reserved",
        ),
        _command(
            "copy",
            "/copy",
            "copy the latest response",
            search_terms=("clipboard",),
            availability="reserved",
        ),
        _command(
            "status",
            "/status",
            "show provider, model, and context status",
            search_terms=("info", "diagnostics", "current model"),
            availability="reserved",
        ),
        _command(
            "usage",
            "/usage",
            "show token and cost usage",
            search_terms=("tokens", "cost", "accounting"),
            availability="reserved",
        ),
        _command(
            "theme",
            "/theme",
            "select a visual theme",
            candidate_names=("themes",),
            search_terms=("colors", "appearance", "style"),
            availability="reserved",
        ),
        _command(
            "editor",
            "/editor",
            "compose a prompt in an external editor",
            search_terms=("edit prompt", "external editor"),
            availability="reserved",
        ),
        _command(
            "undo",
            "/undo",
            "undo a conversation edit",
            search_terms=("revert message", "undo turn"),
            availability="reserved",
        ),
        _command(
            "redo",
            "/redo",
            "redo a conversation edit",
            search_terms=("restore message", "redo turn"),
            availability="reserved",
        ),
        _command(
            "fork",
            "/fork",
            "fork the current conversation",
            search_terms=("branch session", "fork conversation"),
        ),
        _command(
            "tree",
            "/tree",
            "navigate conversation branches",
            search_terms=("branches", "session tree"),
            availability="reserved",
        ),
        _command(
            "extensions",
            "/extensions",
            "inspect and manage extensions",
            candidate_names=("plugins",),
            search_terms=("extension list",),
            availability="reserved",
        ),
        _command(
            "reload",
            "/reload",
            "reload dynamic capabilities",
            search_terms=("refresh skills", "refresh extensions"),
            availability="reserved",
        ),
        _command(
            "init",
            "/init",
            "set up project instructions",
            search_terms=("initialize project", "instructions"),
            availability="reserved",
        ),
    )
)

for _setting_name, _description in (
    ("temperature", "change active provider temperature"),
    ("max-completion-tokens", "change active provider completion limit"),
    ("max-output-tokens", "change active provider output limit"),
    ("max-tokens", "change active provider token limit"),
    ("supports-tools", "toggle native tool support"),
    ("supports-stream", "toggle streaming capability"),
    ("supports-chat-completions", "toggle /chat/completions URL suffix"),
    ("base-url", "change active provider base URL"),
    ("api-key", "change active provider API key"),
    ("response-format", "change active provider response format"),
    ("provider-name", "rename active provider"),
):
    _COMMAND_DEFINITIONS.append(
        _command(
            f"provider-setting:{_setting_name}",
            f"/{_setting_name}",
            _description,
            availability="hidden-compatibility",
            setting_key="name" if _setting_name == "provider-name" else _setting_name,
        )
    )


DEFAULT_COMMAND_CATALOG = CommandCatalog(_COMMAND_DEFINITIONS)