"""Application-owned discovery and assembly of local agent resources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
from collections.abc import Sequence
from typing import Literal

from peon.agent import AgentContext, AgentMessage

ResourceDiagnosticKind = Literal[
    "missing",
    "malformed",
    "unreadable",
    "duplicate",
    "disabled",
]


@dataclass(frozen=True, slots=True)
class ResourceDiagnostic:
    kind: ResourceDiagnosticKind
    path: Path
    message: str


@dataclass(frozen=True, slots=True)
class SkillResource:
    name: str
    description: str
    content: str
    path: Path
    base_directory: Path
    source: str


@dataclass(frozen=True, slots=True)
class ContextResource:
    path: Path
    content: str
    source: str


@dataclass(frozen=True, slots=True)
class ResourceInventory:
    skills: tuple[SkillResource, ...] = ()
    context_files: tuple[ContextResource, ...] = ()
    system_prompt: str = ""
    system_prompt_source: Path | None = None
    append_system_prompt: tuple[str, ...] = ()
    append_system_prompt_sources: tuple[Path, ...] = ()
    diagnostics: tuple[ResourceDiagnostic, ...] = ()
    effective_system_prompt: str = ""

    @property
    def sources(self) -> tuple[Path, ...]:
        resources: tuple[SkillResource | ContextResource, ...] = (
            *self.skills,
            *self.context_files,
        )
        return tuple(
            resource.path
            for resource in resources
        )

    def find_skill(self, name: str) -> SkillResource | None:
        normalized_name = name.casefold()
        return next(
            (skill for skill in self.skills if skill.name.casefold() == normalized_name),
            None,
        )

    def diagnostic_summary(self) -> str:
        if not self.diagnostics:
            return "no resource diagnostics"
        counts: dict[str, int] = {}
        for diagnostic in self.diagnostics:
            counts[diagnostic.kind] = counts.get(diagnostic.kind, 0) + 1
        return ", ".join(
            f"{kind}={counts[kind]}" for kind in sorted(counts)
        )

    def startup_summary(self) -> tuple[str, ...]:
        lines: list[str] = []
        if self.context_files:
            lines.extend(
                [
                    "[Context]",
                    *(f"  {resource.path.name}" for resource in self.context_files),
                ]
            )
        if self.skills:
            if lines:
                lines.append("")
            lines.extend(
                [
                    "[Skills]",
                    f"  {', '.join(skill.name for skill in self.skills)}",
                ]
            )
        if self.system_prompt_source is not None:
            if lines:
                lines.append("")
            lines.append(f"  system prompt: {self.system_prompt_source}")
        elif self.system_prompt:
            if lines:
                lines.append("")
            lines.append("  system prompt: inline override")
        lines.extend(
            f"  append prompt: {path}"
            for path in self.append_system_prompt_sources
        )
        if self.diagnostics:
            if lines:
                lines.append("")
            lines.append(f"Resource diagnostics: {self.diagnostic_summary()}")
            lines.extend(
                f"  {diagnostic.kind}: {diagnostic.path} ({diagnostic.message})"
                for diagnostic in self.diagnostics
            )
        return tuple(lines)


class ResourceLoader:
    """Load trusted local resources without coupling them to the agent loop."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        global_root: Path | None = None,
        include_skills: bool = True,
        include_context_files: bool = True,
        trust_project: bool = True,
        skill_paths: Sequence[Path] = (),
        context_paths: Sequence[Path] = (),
        system_prompt: str | None = None,
        system_prompt_path: Path | None = None,
        append_system_prompt: Sequence[str] = (),
        append_system_prompt_paths: Sequence[Path] = (),
    ) -> None:
        self.root = (root or Path.cwd()).resolve()
        self.global_root = (
            global_root.resolve()
            if global_root is not None
            else _default_global_root()
        )
        self.include_skills = include_skills
        self.include_context_files = include_context_files
        self.trust_project = trust_project
        self.skill_paths = tuple(path.resolve() for path in skill_paths)
        self.context_paths = tuple(path.resolve() for path in context_paths)
        self.system_prompt_override = system_prompt
        self.system_prompt_path = (
            system_prompt_path.resolve()
            if system_prompt_path is not None
            else None
        )
        self.append_system_prompt = tuple(append_system_prompt)
        self.append_system_prompt_paths = tuple(
            path.resolve() for path in append_system_prompt_paths
        )

    def load(self) -> ResourceInventory:
        diagnostics: list[ResourceDiagnostic] = []
        skills = self._load_skills(diagnostics)
        context_files = self._load_context_files(diagnostics)
        system_prompt, system_prompt_source = self._load_system_prompt(diagnostics)
        append_prompts, append_prompt_sources = self._load_append_prompts(diagnostics)
        effective_prompt = build_effective_system_prompt(
            system_prompt,
            append_prompts,
            context_files,
            skills,
        )
        return ResourceInventory(
            skills=skills,
            context_files=context_files,
            system_prompt=system_prompt,
            system_prompt_source=system_prompt_source,
            append_system_prompt=append_prompts,
            append_system_prompt_sources=append_prompt_sources,
            diagnostics=tuple(diagnostics),
            effective_system_prompt=effective_prompt,
        )

    def _load_skills(
        self,
        diagnostics: list[ResourceDiagnostic],
    ) -> tuple[SkillResource, ...]:
        candidates: list[tuple[Path, str]] = []
        discovered = self._skill_directories()
        if self.include_skills:
            candidates.extend(
                (path, source)
                for path, source in discovered
                if self.trust_project or source != "project"
            )
            if not self.trust_project:
                for path, source in discovered:
                    if source == "project":
                        diagnostics.append(
                            ResourceDiagnostic(
                                "disabled",
                                path,
                                "project skill is not trusted",
                            )
                        )
        else:
            for path, _source in discovered:
                diagnostics.append(
                    ResourceDiagnostic(
                        "disabled", path, "skill discovery is disabled"
                    )
                )
        candidates.extend((path, "explicit") for path in self.skill_paths)
        loaded_skills: dict[str, SkillResource] = {}
        for directory, source in candidates:
            path = directory / "SKILL.md" if directory.is_dir() else directory
            resource = _read_skill(path, source, diagnostics)
            if resource is None:
                continue
            key = resource.name.casefold()
            if key in loaded_skills:
                diagnostics.append(
                    ResourceDiagnostic("duplicate", path, f"skill '{resource.name}' overrides an earlier resource")
                )
            loaded_skills[key] = resource
        return tuple(
            sorted(loaded_skills.values(), key=lambda skill: skill.name.casefold())
        )

    def _skill_directories(self) -> tuple[tuple[Path, str], ...]:
        candidates: list[tuple[Path, str]] = []
        for directory in (
            self.global_root / "skills",
            self.global_root / ".agents" / "skills",
        ):
            candidates.extend(
                (path, "global")
                for path in _skill_directories_in(directory)
            )
        for directory in reversed(_ancestor_directories(self.root)):
            candidates.extend(
                (path, "project")
                for path in _skill_directories_in(directory / ".agents" / "skills")
            )
        return tuple(
            (path.resolve(), source)
            for path, source in candidates
        )

    def _load_context_files(
        self,
        diagnostics: list[ResourceDiagnostic],
    ) -> tuple[ContextResource, ...]:
        candidates: list[tuple[Path, str]] = []
        discovered = self._context_file_candidates()
        if self.include_context_files:
            candidates.extend(
                (path, source)
                for path, source in discovered
                if self.trust_project or source != "project"
            )
            if not self.trust_project:
                for path, source in discovered:
                    if source == "project":
                        diagnostics.append(
                            ResourceDiagnostic(
                                "disabled",
                                path,
                                "project context file is not trusted",
                            )
                        )
        else:
            for path, _source in discovered:
                diagnostics.append(
                    ResourceDiagnostic(
                        "disabled", path, "context-file discovery is disabled"
                    )
                )
        candidates.extend((path, "explicit") for path in self.context_paths)
        resources: list[ContextResource] = []
        seen: set[Path] = set()
        for path, source in candidates:
            if path in seen:
                diagnostics.append(
                    ResourceDiagnostic("duplicate", path, "context file was discovered more than once")
                )
                continue
            seen.add(path)
            try:
                content = path.read_text(encoding="utf-8")
            except FileNotFoundError:
                diagnostics.append(ResourceDiagnostic("missing", path, "context file was not found"))
            except (OSError, UnicodeError) as error:
                diagnostics.append(ResourceDiagnostic("unreadable", path, str(error)))
            else:
                resources.append(ContextResource(path, content, source))
        return tuple(resources)

    def _context_file_candidates(self) -> tuple[tuple[Path, str], ...]:
        candidates: list[tuple[Path, str]] = []
        global_candidates = _context_paths(self.global_root)
        candidates.extend((path, "global") for path in global_candidates)
        for directory in reversed(_ancestor_directories(self.root)):
            candidates.extend(
                (path, "project") for path in _context_paths(directory)
            )
        return tuple(
            (path.resolve(), source)
            for path, source in candidates
        )

    def _load_system_prompt(
        self,
        diagnostics: list[ResourceDiagnostic],
    ) -> tuple[str, Path | None]:
        if self.system_prompt_override is not None:
            return self.system_prompt_override, None
        if self.system_prompt_path is not None:
            diagnostic_count = len(diagnostics)
            prompt = _read_text_resource(
                self.system_prompt_path,
                diagnostics,
                "system prompt",
            )
            return (
                prompt,
                self.system_prompt_path
                if len(diagnostics) == diagnostic_count
                else None,
            )
        candidates = [
            self.global_root / "SYSTEM.md",
            *(
                (
                    directory / "SYSTEM.md"
                    for directory in reversed(_ancestor_directories(self.root))
                )
                if self.trust_project
                else ()
            ),
        ]
        existing = [path for path in candidates if path.is_file()]
        for path in existing[:-1]:
            diagnostics.append(
                ResourceDiagnostic(
                    "duplicate",
                    path,
                    "system prompt is overridden by a later source",
                )
            )
        source = existing[-1] if existing else None
        if source is None:
            return "", None
        diagnostic_count = len(diagnostics)
        prompt = _read_text_resource(source, diagnostics, "system prompt")
        return prompt, source if len(diagnostics) == diagnostic_count else None

    def _load_append_prompts(
        self,
        diagnostics: list[ResourceDiagnostic],
    ) -> tuple[tuple[str, ...], tuple[Path, ...]]:
        prompts: list[str] = []
        sources: list[Path] = []
        candidates = [
            self.global_root / "APPEND_SYSTEM.md",
            *(
                (
                    directory / "APPEND_SYSTEM.md"
                    for directory in reversed(_ancestor_directories(self.root))
                )
                if self.trust_project
                else ()
            ),
            *self.append_system_prompt_paths,
        ]
        seen: set[Path] = set()
        for path in candidates:
            if path in seen:
                diagnostics.append(
                    ResourceDiagnostic(
                        "duplicate",
                        path,
                        "append prompt was supplied more than once",
                    )
                )
                continue
            seen.add(path)
            if path.is_file() or path in self.append_system_prompt_paths:
                prompt = _read_text_resource(path, diagnostics, "append prompt")
                if prompt:
                    prompts.append(prompt)
                    sources.append(path)
        prompts.extend(self.append_system_prompt)
        return tuple(prompt for prompt in prompts if prompt), tuple(sources)


def build_effective_system_prompt(
    system_prompt: str,
    append_system_prompt: Sequence[str],
    context_files: Sequence[ContextResource],
    skills: Sequence[SkillResource],
) -> str:
    sections: list[str] = []
    if system_prompt:
        sections.append(system_prompt.rstrip())
    if context_files:
        sections.append(
            "## Context files\n"
            + "\n\n".join(
                f"### {resource.path}\n{resource.content.rstrip()}"
                for resource in context_files
            )
        )
    if skills:
        sections.append(
            "## Available skills\n"
            + "\n".join(
                f'<skill name="{skill.name}" description="{_prompt_value(skill.description)}" '
                f'location="{skill.path}" />'
                for skill in skills
            )
        )
    sections.extend(prompt.rstrip() for prompt in append_system_prompt if prompt)
    return "\n\n".join(section for section in sections if section)


def apply_resource_prompt(
    context: AgentContext,
    resources: ResourceInventory,
) -> None:
    """Insert the assembled prompt once into an application-owned context."""
    prompt = resources.effective_system_prompt
    if not prompt:
        return
    if any(
        message.role == "system" and message.content == prompt
        for message in context.messages
    ):
        return
    context.messages.insert(0, AgentMessage(role="system", content=prompt))


def load_skill_into_context(
    context: AgentContext,
    skill: SkillResource,
) -> None:
    instruction = f"## Skill: {skill.name}\n\n{skill.content}".strip()
    if any(
        message.role == "system" and message.content == instruction
        for message in context.messages
    ):
        return
    context.messages.append(AgentMessage(role="system", content=instruction))


def conversation_messages_without_resource_prompt(
    messages: Sequence[AgentMessage],
    resources: ResourceInventory | None,
) -> tuple[AgentMessage, ...]:
    if resources is None:
        return tuple(messages)
    return tuple(
        message
        for message in messages
        if not (
            message.role == "system"
            and message.content == resources.effective_system_prompt
        )
    )


def _default_global_root() -> Path:
    configured = os.environ.get("PEON_RESOURCE_DIR")
    return Path(configured).expanduser().resolve() if configured else Path.home() / ".peon"


def _ancestor_directories(root: Path) -> tuple[Path, ...]:
    directories: list[Path] = []
    current = root
    home = Path.home().resolve()
    while True:
        if current != home:
            directories.append(current)
        if current.parent == current or current == home:
            break
        current = current.parent
    return tuple(directories)


def _skill_directories_in(root: Path) -> tuple[Path, ...]:
    if not root.is_dir():
        return ()
    return tuple(
        path
        for path in sorted(root.iterdir(), key=lambda item: item.name.casefold())
        if path.is_dir() and (path / "SKILL.md").exists()
    )


def _context_paths(root: Path) -> tuple[Path, ...]:
    return tuple(
        path for path in (root / "AGENTS.md", root / "CLAUDE.md") if path.is_file()
    )


def _read_skill(
    path: Path,
    source: str,
    diagnostics: list[ResourceDiagnostic],
) -> SkillResource | None:
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        diagnostics.append(ResourceDiagnostic("missing", path, "skill file was not found"))
        return None
    except (OSError, UnicodeError) as error:
        diagnostics.append(ResourceDiagnostic("unreadable", path, str(error)))
        return None
    metadata, body, malformed = _parse_skill(content)
    if malformed:
        diagnostics.append(ResourceDiagnostic("malformed", path, malformed))
        return None
    name = metadata.get("name") or path.parent.name
    description = metadata.get("description", "")
    return SkillResource(name, description, body, path, path.parent, source)


def _parse_skill(content: str) -> tuple[dict[str, str], str, str | None]:
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    if not content.startswith("---\n"):
        return {}, content, None
    closing = content.find("\n---", 4)
    if closing < 0:
        return {}, "", "skill front matter is not closed"
    front_matter = content[4:closing].splitlines()
    metadata: dict[str, str] = {}
    index = 0
    while index < len(front_matter):
        line = front_matter[index]
        if not line.strip():
            index += 1
            continue
        if line[0].isspace():
            return {}, "", "skill front matter contains an invalid field"
        key, separator, value = line.partition(":")
        if not separator or not key.strip():
            return {}, "", "skill front matter contains an invalid field"
        normalized_value = value.strip().strip('"\'')
        index += 1
        if normalized_value[:1] in {">", "|"} and normalized_value[1:].strip() in {"", "+", "-"}:
            block_lines: list[str] = []
            while index < len(front_matter):
                continuation = front_matter[index]
                if not continuation.strip():
                    block_lines.append("")
                    index += 1
                    continue
                if not continuation[0].isspace():
                    break
                block_lines.append(continuation)
                index += 1
            metadata[key.strip().casefold()] = _parse_block_scalar(
                normalized_value[0],
                normalized_value[1:].strip(),
                block_lines,
            )
            continue
        metadata[key.strip().casefold()] = normalized_value
    body = content[closing + len("\n---") :]
    if body.startswith("\n"):
        body = body[1:]
    return metadata, body, None


def _parse_block_scalar(style: str, chomping: str, lines: list[str]) -> str:
    non_empty_indents = [
        len(line) - len(line.lstrip())
        for line in lines
        if line.strip()
    ]
    indent = min(non_empty_indents, default=0)
    normalized_lines = [line[indent:] if line.strip() else "" for line in lines]
    if style == "|":
        value = "\n".join(normalized_lines)
    else:
        folded: list[str] = []
        paragraph: list[str] = []
        for line in normalized_lines:
            if line:
                paragraph.append(line.strip())
            elif paragraph:
                folded.append(" ".join(paragraph))
                paragraph = []
                folded.append("")
        if paragraph:
            folded.append(" ".join(paragraph))
        value = "\n".join(folded)
    if chomping != "-":
        value += "\n"
    return value


def _read_text_resource(
    path: Path,
    diagnostics: list[ResourceDiagnostic],
    label: str,
) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        diagnostics.append(ResourceDiagnostic("missing", path, f"{label} was not found"))
    except (OSError, UnicodeError) as error:
        diagnostics.append(ResourceDiagnostic("unreadable", path, str(error)))
    return ""


def _prompt_value(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")