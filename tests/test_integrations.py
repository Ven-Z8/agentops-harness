from pathlib import Path

from typer.testing import CliRunner

from app.cli import app
from app.core.integrations import install_cursor_pack, write_goose_recipe


def test_install_cursor_pack_writes_commands_and_rules(tmp_path: Path) -> None:
    result = install_cursor_pack(tmp_path)

    assert result.created_files == [
        ".cursor/commands/agentops-handoff.md",
        ".cursor/commands/agentops-report.md",
        ".cursor/commands/agentops-run.md",
        ".cursor/commands/agentops-scan.md",
        ".cursor/rules/agentops-harness.mdc",
    ]
    assert (tmp_path / ".cursor/commands/agentops-run.md").exists()
    assert "agentops run" in (tmp_path / ".cursor/commands/agentops-run.md").read_text()
    assert "Cursor owns planning and review" in (
        tmp_path / ".cursor/rules/agentops-harness.mdc"
    ).read_text()


def test_write_goose_recipe_creates_valid_yaml_shape(tmp_path: Path) -> None:
    recipe_path = write_goose_recipe(tmp_path)

    content = recipe_path.read_text()

    assert recipe_path == tmp_path / ".goose/recipes/agentops-harness.yaml"
    assert 'title: "AgentOps Harness Evaluator"' in content
    assert "goose_provider" in content
    assert "uv run --extra dev agentops run" in content
    assert "agentops-mcp" in content
    assert "Risk assessment" in content


def test_cli_installs_cursor_pack(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["integrations", "cursor", "--repo", str(tmp_path)])

    assert result.exit_code == 0
    assert "Installed Cursor integration" in result.stdout
    assert (tmp_path / ".cursor/commands/agentops-scan.md").exists()


def test_cli_writes_goose_recipe(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["integrations", "goose", "--repo", str(tmp_path)])

    assert result.exit_code == 0
    assert "Wrote Goose recipe" in result.stdout
    assert (tmp_path / ".goose/recipes/agentops-harness.yaml").exists()
