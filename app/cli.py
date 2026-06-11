from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel

from app.agents.planner import Planner
from app.agents.repo_scanner import RepoScanner
from app.core.config import settings
from app.core.graph import run_harness
from app.core.handoff import (
    draft_worker_handoff,
    handoff_document_json,
    render_handoff_markdown,
    worker_handoff_from_run,
)
from app.core.integrations import install_cursor_pack, write_goose_recipe
from app.core.llm import build_runtime_llm_client, provider_status
from app.core.portfolio import (
    build_portfolio_episode,
    render_portfolio_episode_markdown,
    write_portfolio_episode,
)
from app.core.repo_graph import RepoGraphBuilder
from app.core.run_artifacts import artifact_path_for_run, export_artifact_bundle
from app.core.storage import RunStorage
from app.core.workload import evaluate_workload_gates, load_workload_manifest

app = typer.Typer(help="Local-first coding-agent orchestration and evaluation harness.")
integrations_app = typer.Typer(help="Install IDE/agent integrations for AgentOps Harness.")
providers_app = typer.Typer(help="Inspect and test LLM providers.")
handoff_app = typer.Typer(
    help="Export deterministic packets for Cursor/Codex/CLI coding workers.",
)
workload_app = typer.Typer(help="Validate portfolio workload manifests and gate checks.")
portfolio_app = typer.Typer(help="Package harness runs as portfolio evidence.")
artifacts_app = typer.Typer(help="Inspect and export per-run artifact folders.")
app.add_typer(integrations_app, name="integrations")
app.add_typer(providers_app, name="providers")
app.add_typer(handoff_app, name="handoff")
app.add_typer(workload_app, name="workload")
app.add_typer(portfolio_app, name="portfolio")
app.add_typer(artifacts_app, name="artifacts")
console = Console()


@app.command()
def init() -> None:
    """Create local AgentOps run storage."""
    settings.run_storage.parent.mkdir(parents=True, exist_ok=True)
    settings.run_storage.touch(exist_ok=True)
    console.print(f"Initialized AgentOps Harness storage at {settings.run_storage}")


@app.command()
def scan(
    repo: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False, help="Repository path."),
    ],
) -> None:
    """Profile a local repository."""
    profile = RepoScanner().scan(repo)
    repo_graph = RepoGraphBuilder().build(repo)
    payload = profile.model_dump(mode="json")
    payload["repo_graph"] = repo_graph.model_dump(mode="json")
    console.print_json(data=payload)


@app.command()
def plan(
    repo: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False, help="Repository path."),
    ],
    task: Annotated[str, typer.Option(help="Engineering task to plan.")],
) -> None:
    """Create a structured implementation plan."""
    profile = RepoScanner().scan(repo)
    repo_graph = RepoGraphBuilder().build(repo)
    implementation_plan = Planner().create_plan(task, profile, repo_graph=repo_graph)
    console.print_json(implementation_plan.model_dump_json())


@app.command()
def run(
    repo: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False, help="Repository path."),
    ],
    task: Annotated[str, typer.Option(help="Engineering task to analyze.")],
    storage: Annotated[Path, typer.Option(help="Run history JSONL path.")] = settings.run_storage,
    goal: Annotated[
        str | None, typer.Option("--goal", help="Intent-graph goal id this run targets.")
    ] = None,
    workspace: Annotated[
        str,
        typer.Option("--workspace", help="Execution workspace: local (default) or docker."),
    ] = "local",
    sandbox: Annotated[
        bool,
        typer.Option("--sandbox/--no-sandbox", help="Run worker in full-isolation Docker sandbox."),
    ] = False,
    max_attempts: Annotated[
        int,
        typer.Option("--max-attempts", help="Maximum retry attempts for the validation loop."),
    ] = 2,
) -> None:
    """Run the full AgentOps Harness pipeline."""
    workspace_kind = "docker" if sandbox else workspace
    isolation = "full" if sandbox else "validation"
    record = run_harness(
        repo_path=repo,
        task=task,
        storage_path=storage,
        llm_client=build_runtime_llm_client(settings),
        target_goal_id=goal,
        workspace_kind=workspace_kind,
        isolation=isolation,
        max_attempts=max_attempts,
    )
    console.print(Panel(record.final_report.markdown, title=f"Run {record.run_id}"))


@app.command()
def edit(
    repo: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False, help="Repository path."),
    ],
    task: Annotated[str, typer.Option(help="Engineering task to hand to the worker.")],
    worker_command: Annotated[
        str | None,
        typer.Option(help="External worker command template. Supports {repo_path} and {task}."),
    ] = None,
    worker_type: Annotated[
        str | None,
        typer.Option(help="Built-in worker type: claude, codex, or opencode."),
    ] = None,
    storage: Annotated[Path, typer.Option(help="Run history JSONL path.")] = settings.run_storage,
    worker_timeout_seconds: Annotated[
        int,
        typer.Option(help="Maximum seconds to wait for the worker command."),
    ] = 300,
    allow_dirty: Annotated[
        bool,
        typer.Option(help="Allow worker runs when the target repo already has changes."),
    ] = False,
    goal: Annotated[
        str | None, typer.Option("--goal", help="Intent-graph goal id this run targets.")
    ] = None,
    sandbox: Annotated[
        bool,
        typer.Option("--sandbox/--no-sandbox", help="Run worker in full-isolation Docker sandbox."),
    ] = False,
    max_attempts: Annotated[
        int,
        typer.Option("--max-attempts", help="Maximum retry attempts for the validation loop."),
    ] = 2,
) -> None:
    """Run an explicit external worker, then validate and report its diff.

    Use --worker-command for arbitrary CLI workers (Cursor, Codex, etc.) or
    --worker-type claude/codex/opencode to delegate to a built-in CLI worker.
    Use --sandbox to run the worker inside a full-isolation Docker container so
    denied writes never reach the host filesystem.
    """
    if worker_command is None and worker_type is None:
        raise typer.BadParameter(
            "Provide either --worker-command or --worker-type (e.g. --worker-type claude)."
        )
    workspace_kind = "docker" if sandbox else "local"
    isolation = "full" if sandbox else "validation"
    record = run_harness(
        repo_path=repo,
        task=task,
        storage_path=storage,
        llm_client=build_runtime_llm_client(settings),
        worker_command=worker_command,
        worker_type=worker_type,
        worker_timeout_seconds=worker_timeout_seconds,
        allow_dirty=allow_dirty,
        target_goal_id=goal,
        workspace_kind=workspace_kind,
        isolation=isolation,
        max_attempts=max_attempts,
    )
    console.print(Panel(record.final_report.markdown, title=f"Run {record.run_id}"))


@app.command()
def report(
    run_id: Annotated[str, typer.Option(help="Run identifier.")],
    storage: Annotated[Path, typer.Option(help="Run history JSONL path.")] = settings.run_storage,
) -> None:
    """Print a saved run report."""
    record = RunStorage(storage).get(run_id)
    console.print(Panel(record.final_report.markdown, title=f"Run {record.run_id}"))


@artifacts_app.command("path")
def show_artifact_path(
    run_id: Annotated[str, typer.Option(help="Run identifier.")],
    storage: Annotated[Path, typer.Option(help="Run history path.")] = settings.run_storage,
) -> None:
    """Print the artifact directory for a saved run."""
    RunStorage(storage).get(run_id)
    artifact_dir = artifact_path_for_run(storage, run_id)
    typer.echo(str(artifact_dir))


@artifacts_app.command("export")
def export_artifacts(
    run_id: Annotated[str, typer.Option(help="Run identifier.")],
    storage: Annotated[Path, typer.Option(help="Run history path.")] = settings.run_storage,
    output_file: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write bundle to this zip file."),
    ] = None,
) -> None:
    """Export a run artifact directory as a zip bundle."""
    RunStorage(storage).get(run_id)
    artifact_dir = artifact_path_for_run(storage, run_id)
    bundle = output_file or artifact_dir.with_suffix(".zip")
    export_artifact_bundle(artifact_dir, bundle)
    typer.echo(f"Exported run artifacts to {bundle}")


@handoff_app.command("export")
def export_handoff(
    run_id: Annotated[str, typer.Option(help="Persisted harness run identifier.")],
    storage: Annotated[Path, typer.Option(help="Run history path.")] = settings.run_storage,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit structured JSON envelope (includes markdown field)."),
    ] = False,
    output_file: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write to file instead of stdout."),
    ] = None,
) -> None:
    """Emit a deterministic worker packet built from an existing run."""
    record = RunStorage(storage).get(run_id)
    packet = worker_handoff_from_run(record)
    if json_output:
        text = json.dumps(handoff_document_json(packet), indent=2, ensure_ascii=False) + "\n"
    else:
        text = render_handoff_markdown(packet)
    if output_file:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(text, encoding="utf-8")
        console.print(f"Wrote worker handoff to {output_file}")
    else:
        console.print(text, soft_wrap=True)


@handoff_app.command("draft")
def draft_handoff_packet(
    repo: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False, help="Repository path."),
    ],
    task: Annotated[str, typer.Option(help="Engineering task to describe for the worker.")],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit structured JSON envelope."),
    ] = False,
    output_file: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write packet to disk."),
    ] = None,
) -> None:
    """Produce planner+scanner-only packet before invoking an external worker."""
    packet = draft_worker_handoff(
        repo_path=repo,
        task=task,
        llm_client=build_runtime_llm_client(settings),
    )

    if json_output:
        text = json.dumps(handoff_document_json(packet), indent=2, ensure_ascii=False) + "\n"
    else:
        text = render_handoff_markdown(packet)
    if output_file:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(text, encoding="utf-8")
        console.print(f"Draft handoff saved to {output_file}")
    else:
        console.print(text, soft_wrap=True)


@workload_app.command("validate")
def validate_workload_manifest(
    manifest_file: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, help=".yaml workload spec."),
    ],
    repo_base: Annotated[
        Path,
        typer.Option(
            "--repo-base",
            exists=True,
            file_okay=False,
            help="Directory used to resolve relative repo paths declared in the manifest.",
        ),
    ] = Path("."),
) -> None:
    """Parse a workload manifest YAML and optionally verify referenced repo folders exist."""
    manifest = load_workload_manifest(manifest_file)
    target = repo_base / manifest.repo
    resolved = target.resolve()
    exists = resolved.is_dir()
    console.print_json(
        data=
        {
            "name": manifest.name,
            "manifest": str(manifest_file),
            "repo_declared": manifest.repo,
            "repo_resolves_to": str(resolved),
            "repo_exists_on_disk": exists,
            "gates": manifest.expected.model_dump(),
        },
    )


@workload_app.command("check")
def workload_gate_check(
    manifest_file: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, help="Workload YAML manifest."),
    ],
    run_id: Annotated[str, typer.Option(help="Run identifier produced by harness.")],
    storage: Annotated[Path, typer.Option(help="Run history path.")] = settings.run_storage,
) -> None:
    """Evaluate declared gates for a persisted run."""
    manifest = load_workload_manifest(manifest_file)
    record = RunStorage(storage).get(run_id)
    result = evaluate_workload_gates(record, manifest)
    console.print_json(
        data=
        {
            "run_id": run_id,
            "workload": manifest.name,
            "passed": result.passed,
            "reasons": result.reasons,
        },
    )
    if not result.passed:
        raise typer.Exit(code=2)


@portfolio_app.command("package")
def package_portfolio_episode(
    run_id: Annotated[str, typer.Option(help="Run identifier produced by harness.")],
    storage: Annotated[Path, typer.Option(help="Run history path.")] = settings.run_storage,
    workload: Annotated[
        Path | None,
        typer.Option(
            "--workload",
            "-w",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Optional workload manifest used to evaluate portfolio gates.",
        ),
    ] = None,
    output_file: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write Markdown package to file."),
    ] = None,
) -> None:
    """Create a viewer-facing evidence package from a completed harness run."""
    record = RunStorage(storage).get(run_id)
    manifest = load_workload_manifest(workload) if workload else None
    episode = build_portfolio_episode(record, manifest)
    if output_file:
        write_portfolio_episode(episode, output_file)
        console.print(f"Wrote portfolio episode to {output_file}")
    else:
        console.print(render_portfolio_episode_markdown(episode), soft_wrap=True)


@integrations_app.command("cursor")
def install_cursor_integration(
    repo: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False, help="Repository path to install into."),
    ] = Path("."),
) -> None:
    """Install Cursor commands and rules for AgentOps Harness."""
    result = install_cursor_pack(repo)
    console.print(f"Installed Cursor integration with {len(result.created_files)} files:")
    for path in result.created_files:
        console.print(f"- {path}")


@integrations_app.command("goose")
def install_goose_integration(
    repo: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False, help="Repository path to install into."),
    ] = Path("."),
) -> None:
    """Write a Goose recipe that uses AgentOps Harness for validation."""
    recipe_path = write_goose_recipe(repo)
    console.print(f"Wrote Goose recipe: {recipe_path}")


@providers_app.command("status")
def show_provider_status() -> None:
    """Show configured LLM provider without making a network call."""
    console.print_json(data=provider_status(settings))


@providers_app.command("ping")
def ping_provider(
    prompt: Annotated[
        str,
        typer.Option(help="Small prompt to send to the configured provider."),
    ] = "Reply with: AgentOps provider ready.",
) -> None:
    """Make a real provider call to verify OpenRouter/OpenAI credentials."""
    llm_client = build_runtime_llm_client(settings)
    if llm_client is None:
        raise typer.BadParameter(
            "AGENTOPS_LLM_PROVIDER is mock. Set it to openrouter or openai first."
        )
    console.print(llm_client.generate_text(prompt))
