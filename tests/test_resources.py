from pathlib import Path

from peon.agent import AgentContext, AgentMessage
from peon.app.resources import ResourceLoader
from peon.app.resources import apply_resource_prompt


def test_resource_loader_discovers_skills_context_and_effective_prompt(
    tmp_path: Path,
) -> None:
    global_root = tmp_path / "global"
    project_parent = tmp_path / "workspace"
    project_root = project_parent / "project"
    (global_root / "skills" / "shared").mkdir(parents=True)
    (project_parent / ".agents" / "skills" / "parent").mkdir(parents=True)
    (project_root / ".agents" / "skills" / "shared").mkdir(parents=True)
    project_root.mkdir(parents=True, exist_ok=True)

    (global_root / "skills" / "shared" / "SKILL.md").write_text(
        "---\nname: shared\ndescription: Global shared skill\n---\n"
        "global body\n",
        encoding="utf-8",
    )
    (project_parent / ".agents" / "skills" / "parent" / "SKILL.md").write_text(
        "---\nname: parent\ndescription: Parent skill\n---\nparent body\n",
        encoding="utf-8",
    )
    (project_root / ".agents" / "skills" / "shared" / "SKILL.md").write_text(
        "---\nname: shared\ndescription: Project shared skill\n---\nproject body\n",
        encoding="utf-8",
    )
    (global_root / "SYSTEM.md").write_text("global system\n", encoding="utf-8")
    (project_root / "SYSTEM.md").write_text("project system\n", encoding="utf-8")
    (global_root / "APPEND_SYSTEM.md").write_text(
        "global append\n", encoding="utf-8"
    )
    (project_root / "APPEND_SYSTEM.md").write_text(
        "project append\n", encoding="utf-8"
    )
    (global_root / "AGENTS.md").write_text("global context\n", encoding="utf-8")
    (project_parent / "AGENTS.md").write_text("parent context\n", encoding="utf-8")
    (project_root / "AGENTS.md").write_text("project context\n", encoding="utf-8")

    resources = ResourceLoader(project_root, global_root=global_root).load()

    assert [skill.name for skill in resources.skills] == ["parent", "shared"]
    assert resources.skills[-1].description == "Project shared skill"
    assert resources.skills[-1].content.endswith("project body\n")
    assert resources.skills[-1].base_directory == project_root / ".agents" / "skills" / "shared"
    assert [file.path.name for file in resources.context_files] == [
        "AGENTS.md",
        "AGENTS.md",
        "AGENTS.md",
    ]
    assert resources.system_prompt == "project system\n"
    assert resources.append_system_prompt == (
        "global append\n",
        "project append\n",
    )
    assert "<skill name=\"parent\"" in resources.effective_system_prompt
    assert "Project shared skill" in resources.effective_system_prompt
    assert "project body" not in resources.effective_system_prompt
    assert "project context" in resources.effective_system_prompt


def test_resource_startup_summary_lists_skill_names_without_paths(
    tmp_path: Path,
) -> None:
    skill_file = tmp_path / ".agents" / "skills" / "notes" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text(
        "---\nname: notes\ndescription: Note taking\n---\nUse notes.\n",
        encoding="utf-8",
    )

    resources = ResourceLoader(
        tmp_path,
        global_root=tmp_path / "missing-global",
    ).load()

    summary = resources.startup_summary()

    assert "  notes" in summary
    assert str(skill_file) not in "\n".join(summary)


def test_resource_startup_summary_groups_context_before_horizontal_skills(
    tmp_path: Path,
) -> None:
    skill_directory = tmp_path / ".agents" / "skills" / "notes"
    skill_directory.mkdir(parents=True)
    (skill_directory / "SKILL.md").write_text(
        "---\nname: notes\ndescription: Note taking\n---\nUse notes.\n",
        encoding="utf-8",
    )
    (tmp_path / "AGENTS.md").write_text("Project rules\n", encoding="utf-8")

    resources = ResourceLoader(
        tmp_path,
        global_root=tmp_path / "missing-global",
    ).load()

    assert resources.startup_summary() == (
        "[Context]",
        "  AGENTS.md",
        "",
        "[Skills]",
        "  notes",
    )


def test_resource_loader_accepts_folded_skill_description(tmp_path: Path) -> None:
    skill_file = tmp_path / ".agents" / "skills" / "notes" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text(
        "---\nname: notes\ndescription: >\n"
        "  Note taking workflows.\n"
        "  Use when organizing notes.\n"
        "license: MIT\n---\nUse notes.\n",
        encoding="utf-8",
    )

    resources = ResourceLoader(
        tmp_path,
        global_root=tmp_path / "missing-global",
    ).load()

    assert resources.diagnostics == ()
    assert resources.skills[0].description == (
        "Note taking workflows. Use when organizing notes.\n"
    )


def test_resource_loader_reports_malformed_resources_and_supports_opt_outs(
    tmp_path: Path,
) -> None:
    skill_directory = tmp_path / ".agents" / "skills" / "broken"
    skill_directory.mkdir(parents=True)
    (skill_directory / "SKILL.md").write_text(
        "---\nname: broken\n",
        encoding="utf-8",
    )
    (tmp_path / "AGENTS.md").write_text("project context\n", encoding="utf-8")

    resources = ResourceLoader(
        tmp_path,
        include_skills=False,
        include_context_files=False,
    ).load()

    assert resources.skills == ()
    assert resources.context_files == ()
    assert {diagnostic.kind for diagnostic in resources.diagnostics} == {"disabled"}

    malformed = ResourceLoader(tmp_path).load()
    assert any(diagnostic.kind == "malformed" for diagnostic in malformed.diagnostics)
    assert any(diagnostic.path == skill_directory / "SKILL.md" for diagnostic in malformed.diagnostics)


def test_resource_prompt_is_added_once_to_an_existing_context(tmp_path: Path) -> None:
    (tmp_path / "SYSTEM.md").write_text("system instructions", encoding="utf-8")
    resources = ResourceLoader(tmp_path, global_root=tmp_path / "missing").load()
    context = AgentContext(messages=[AgentMessage(role="user", content="old")])

    apply_resource_prompt(context, resources)
    apply_resource_prompt(context, resources)

    assert context.messages[0] == AgentMessage(
        role="system",
        content="system instructions",
    )
    assert [message.role for message in context.messages] == ["system", "user"]


def test_resource_loader_supports_explicit_paths_trust_and_reload(
    tmp_path: Path,
) -> None:
    project_skill = tmp_path / ".agents" / "skills" / "project"
    project_skill.mkdir(parents=True)
    skill_file = project_skill / "SKILL.md"
    skill_file.write_text("---\nname: project\n---\nfirst\n", encoding="utf-8")
    explicit_context = tmp_path / "explicit.md"
    explicit_context.write_text("explicit context\n", encoding="utf-8")

    loader = ResourceLoader(
        tmp_path,
        global_root=tmp_path / "missing",
        trust_project=False,
        skill_paths=(skill_file,),
        context_paths=(explicit_context,),
    )
    first = loader.load()
    skill_file.write_text("---\nname: project\n---\nsecond\n", encoding="utf-8")
    second = loader.load()

    assert first.skills[0].content == "first\n"
    assert second.skills[0].content == "second\n"
    assert [context.path for context in first.context_files] == [explicit_context]
    assert any(diagnostic.kind == "disabled" for diagnostic in first.diagnostics)


def test_resource_loader_handles_crlf_skill_front_matter_and_prompt_sources(
    tmp_path: Path,
) -> None:
    skill_directory = tmp_path / ".agents" / "skills" / "notes"
    skill_directory.mkdir(parents=True)
    (skill_directory / "SKILL.md").write_bytes(
        b"---\r\nname: notes\r\ndescription: Notes\r\n---\r\nUse notes.\r\n"
    )
    global_root = tmp_path / "global"
    global_root.mkdir()
    (global_root / "SYSTEM.md").write_text("global", encoding="utf-8")
    (tmp_path / "SYSTEM.md").write_text("project", encoding="utf-8")
    (global_root / "APPEND_SYSTEM.md").write_text("append", encoding="utf-8")

    resources = ResourceLoader(tmp_path, global_root=global_root).load()

    assert resources.skills[0].name == "notes"
    assert resources.skills[0].description == "Notes"
    assert resources.system_prompt == "project"
    assert resources.system_prompt_source == tmp_path / "SYSTEM.md"
    assert resources.append_system_prompt_sources == (
        global_root / "APPEND_SYSTEM.md",
    )
    assert any(diagnostic.kind == "duplicate" for diagnostic in resources.diagnostics)


def test_resource_loader_reports_missing_unreadable_and_duplicate_explicit_files(
    tmp_path: Path,
) -> None:
    existing = tmp_path / "context.md"
    existing.write_text("context", encoding="utf-8")
    directory = tmp_path / "directory"
    directory.mkdir()

    resources = ResourceLoader(
        tmp_path,
        global_root=tmp_path / "missing-global",
        context_paths=(existing, existing, tmp_path / "missing.md", directory),
    ).load()

    kinds = {diagnostic.kind for diagnostic in resources.diagnostics}
    assert {"duplicate", "missing", "unreadable"} <= kinds


def test_resource_loader_merges_discovered_and_explicit_append_prompts(
    tmp_path: Path,
) -> None:
    global_root = tmp_path / "global"
    global_root.mkdir()
    discovered = global_root / "APPEND_SYSTEM.md"
    discovered.write_text("discovered", encoding="utf-8")
    explicit = tmp_path / "append.md"
    explicit.write_text("explicit", encoding="utf-8")

    resources = ResourceLoader(
        tmp_path,
        global_root=global_root,
        append_system_prompt_paths=(explicit,),
    ).load()

    assert resources.append_system_prompt == ("discovered", "explicit")
    assert resources.append_system_prompt_sources == (discovered, explicit)


def test_resource_loader_reports_duplicate_discovered_context_files(
    tmp_path: Path,
) -> None:
    context = tmp_path / "AGENTS.md"
    context.write_text("project rules", encoding="utf-8")

    resources = ResourceLoader(
        context.parent,
        global_root=context.parent,
    ).load()

    assert any(
        diagnostic.kind == "duplicate" and diagnostic.path == context
        for diagnostic in resources.diagnostics
    )


def test_resource_loader_project_opt_out_excludes_project_prompt_sources(
    tmp_path: Path,
) -> None:
    global_root = tmp_path / "global"
    project_root = tmp_path / "project"
    global_root.mkdir()
    project_root.mkdir()
    (global_root / "SYSTEM.md").write_text("global system", encoding="utf-8")
    (project_root / "SYSTEM.md").write_text("project system", encoding="utf-8")
    (global_root / "APPEND_SYSTEM.md").write_text("global append", encoding="utf-8")
    (project_root / "APPEND_SYSTEM.md").write_text("project append", encoding="utf-8")

    resources = ResourceLoader(
        project_root,
        global_root=global_root,
        trust_project=False,
    ).load()

    assert resources.system_prompt == "global system"
    assert resources.append_system_prompt == ("global append",)
    assert "project system" not in resources.effective_system_prompt
    assert "project append" not in resources.effective_system_prompt


def test_resource_loader_does_not_report_failed_system_prompt_as_loaded(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing-system.md"

    resources = ResourceLoader(
        tmp_path,
        global_root=tmp_path / "missing-global",
        system_prompt_path=missing,
    ).load()

    assert resources.system_prompt == ""
    assert resources.system_prompt_source is None
    assert any(
        diagnostic.kind == "missing" and diagnostic.path == missing
        for diagnostic in resources.diagnostics
    )
