"""M3 — capability-pack loader.

The loader must turn a pack directory into the exact inputs the inner agent
receives: skills → system-prompt suffix, tools → an allowlisted name list,
hooks → callbacks. Guardrail: pack tools stay terminal/file-only.
"""

import hashlib
from pathlib import Path

import pytest

from app.core.packs.loader import (
    PackError,
    assemble_agent_inputs,
    build_pack_provenance,
    discover_pack,
    load_hook_callables,
    load_pack,
    pack_system_suffix,
    resolve_tool_names,
)
from app.core.packs.selector import select_pack

BUILTIN_DEFAULT_TOOLS = ["terminal", "file_editor", "task_tracker", "grep", "glob", "task_tool_set"]


def _write_pack(
    root: Path,
    *,
    name: str = "demo",
    tools: list[str] | None = None,
    hooks: list[str] | None = None,
    hooks_body: str | None = None,
) -> Path:
    pack_dir = root / name
    (pack_dir / "skills").mkdir(parents=True)
    tool_lines = "\n".join(f"  - {t}" for t in (tools or []))
    hook_lines = "\n".join(f"  - {h}" for h in (hooks or []))
    (pack_dir / "manifest.yaml").write_text(
        f"name: {name}\n"
        f"domain: testing\n"
        f"version: 0.1.0\n"
        f"description: A test pack.\n"
        f"skills:\n  - playbook.md\n"
        f"tools:\n{tool_lines}\n"
        f"hooks:\n{hook_lines}\n",
        encoding="utf-8",
    )
    (pack_dir / "skills" / "playbook.md").write_text(
        "# Playbook\n\nAlways run the migration in small, verified steps.\n", encoding="utf-8"
    )
    if hooks_body is not None:
        (pack_dir / "hooks.py").write_text(hooks_body, encoding="utf-8")
    return pack_dir


def test_load_pack_parses_manifest_and_reads_skills(tmp_path: Path) -> None:
    pack_dir = _write_pack(tmp_path, tools=["terminal", "file_editor"])
    pack = load_pack(pack_dir)

    assert pack.manifest.name == "demo"
    assert pack.manifest.domain == "testing"
    assert [s.name for s in pack.skills] == ["playbook.md"]
    assert "small, verified steps" in pack.skills[0].content


def test_build_pack_provenance_records_exact_manifest_and_resolved_tools(
    tmp_path: Path,
) -> None:
    pack_dir = _write_pack(tmp_path, tools=["terminal", "file_editor"])
    pack = load_pack(pack_dir)

    provenance = build_pack_provenance(pack, ["terminal", "file_editor"])

    assert provenance.name == "demo"
    assert provenance.version == "0.1.0"
    assert provenance.skills == ["playbook.md"]
    assert provenance.resolved_tools == ["terminal", "file_editor"]
    assert provenance.hooks == []
    assert provenance.manifest_sha256 == hashlib.sha256(
        (pack_dir / "manifest.yaml").read_bytes()
    ).hexdigest()


def test_pack_system_suffix_includes_skill_text(tmp_path: Path) -> None:
    pack = load_pack(_write_pack(tmp_path))
    suffix = pack_system_suffix(pack)
    assert "Capability pack: demo" in suffix
    assert "Always run the migration in small, verified steps." in suffix


def test_resolve_tool_names_returns_pack_subset(tmp_path: Path) -> None:
    pack = load_pack(_write_pack(tmp_path, tools=["terminal", "file_editor"]))
    assert resolve_tool_names(pack, BUILTIN_DEFAULT_TOOLS) == ["terminal", "file_editor"]


def test_pack_without_tools_uses_default_set(tmp_path: Path) -> None:
    pack = load_pack(_write_pack(tmp_path, tools=[]))
    assert resolve_tool_names(pack, BUILTIN_DEFAULT_TOOLS) == BUILTIN_DEFAULT_TOOLS


def test_guardrail_rejects_non_terminal_file_tools(tmp_path: Path) -> None:
    with pytest.raises(PackError, match="terminal/file-only"):
        load_pack(_write_pack(tmp_path, tools=["browser"]))


def test_load_hook_callables_imports_and_returns_callables(tmp_path: Path) -> None:
    pack = load_pack(
        _write_pack(
            tmp_path,
            hooks=["on_event"],
            hooks_body="def on_event(event):\n    return 'seen'\n",
        )
    )
    hooks = load_hook_callables(pack)
    assert len(hooks) == 1
    assert hooks[0]("anything") == "seen"


def test_assemble_agent_inputs_folds_pack_into_agent(tmp_path: Path) -> None:
    pack = load_pack(
        _write_pack(
            tmp_path,
            tools=["terminal", "file_editor"],
            hooks=["on_event"],
            hooks_body="def on_event(event):\n    return None\n",
        )
    )
    suffix, tool_names, hooks = assemble_agent_inputs(
        pack, base_system_suffix="BASE_HARNESS_RULES", default_tools=BUILTIN_DEFAULT_TOOLS
    )
    # skill + base both present in what the agent sees
    assert "BASE_HARNESS_RULES" in suffix
    assert "small, verified steps" in suffix
    assert tool_names == ["terminal", "file_editor"]
    assert len(hooks) == 1


def test_assemble_agent_inputs_without_pack_is_baseline() -> None:
    suffix, tool_names, hooks = assemble_agent_inputs(
        None, base_system_suffix="BASE", default_tools=BUILTIN_DEFAULT_TOOLS
    )
    assert suffix == "BASE"
    assert tool_names == BUILTIN_DEFAULT_TOOLS
    assert hooks == []


def test_discover_pack_by_path_and_by_name(tmp_path: Path) -> None:
    pack_dir = _write_pack(tmp_path, name="byname")
    assert discover_pack(str(pack_dir)) == pack_dir
    assert discover_pack("byname", search_root=tmp_path) == pack_dir
    with pytest.raises(PackError, match="not found"):
        discover_pack("missing", search_root=tmp_path)


def test_select_pack_resolves_explicit_and_defaults_to_none(tmp_path: Path) -> None:
    pack_dir = _write_pack(tmp_path, name="picked")
    assert select_pack("picked", search_root=tmp_path) == pack_dir
    assert select_pack(None, task="anything") is None


def test_runner_env_passes_pack_path_to_subprocess() -> None:
    from app.core.workers.openhands_worker import _runner_env

    assert _runner_env(None, "local", "/packs/demo")["OPENHANDS_PACK_PATH"] == "/packs/demo"
    assert "OPENHANDS_PACK_PATH" not in _runner_env(None, "local", None)


def test_shipped_example_pack_loads_and_is_terminal_file_only() -> None:
    pack = load_pack(discover_pack("example"))
    assert pack.manifest.name == "example"
    assert resolve_tool_names(pack, BUILTIN_DEFAULT_TOOLS) == [
        "terminal",
        "file_editor",
        "grep",
        "glob",
    ]
    assert "example pack" in pack_system_suffix(pack).lower()


def test_pydantic_v2_pack_is_bounded_and_inspectable() -> None:
    pack = load_pack(discover_pack("pydantic-v2"))
    tools = resolve_tool_names(pack, BUILTIN_DEFAULT_TOOLS)

    assert pack.manifest.name == "pydantic-v2"
    assert pack.manifest.domain == "python-migration"
    assert pack.manifest.version == "1.0.0"
    assert pack.manifest.skills == ["migration-playbook.md"]
    assert tools == ["terminal", "file_editor", "grep", "glob"]
    assert pack.manifest.hooks == []
