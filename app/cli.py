from __future__ import annotations

import json
import os
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
def serve(
    host: Annotated[str, typer.Option(help="Bind host.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port.")] = 8000,
    storage: Annotated[
        Path | None,
        typer.Option(help="Run storage path (defaults to settings.run_storage)."),
    ] = None,
) -> None:
    """Serve the harness API + operator console (http://<host>:<port>/console)."""
    import uvicorn

    from app.api import create_api

    api = create_api(storage_path=storage) if storage is not None else create_api()
    console.print(f"API docs:    http://{host}:{port}/docs")
    console.print(f"Console:     http://{host}:{port}/console/runs-list.html")
    console.print(f"Cockpit:     http://{host}:{port}/cockpit/")
    uvicorn.run(api, host=host, port=port)


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
        typer.Option(
            help="Built-in worker type: claude, codex, opencode, or openhands. "
            "Defaults to openhands (the inner loop) when neither --worker-type nor "
            "--worker-command is given."
        ),
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
    pack: Annotated[
        str | None,
        typer.Option(
            "--pack",
            help=(
                "Capability pack to equip the openhands worker with (a path or a "
                "built-in pack name, e.g. 'example'). Injects skills/tools/hooks."
            ),
        ),
    ] = None,
) -> None:
    """Run a coding worker, then validate and report its diff.

    Defaults to the OpenHands inner loop (no worker flag needed). Use
    --worker-type claude/codex/opencode for another built-in worker, or
    --worker-command for an arbitrary CLI worker (Cursor, etc.).
    Use --sandbox to run the worker inside a full-isolation Docker container so
    denied writes never reach the host filesystem.
    """
    if worker_command is None and worker_type is None:
        # The inner loop is OpenHands by default — no worker flag needed. The other
        # built-in workers (claude/codex/opencode) and --worker-command remain opt-in.
        worker_type = "openhands"
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
        pack=pack,
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


issues_app = typer.Typer(
    help="Governed runs against real GitHub issues (the flagship path).",
)

# Governed issue runs persist to the workspace-local store. Module-level so
# the positive-contract gate's re-save (AO-D03-01) targets the same storage.
ISSUE_STORAGE_PATH = Path(".agentops/runs.jsonl")


def _spec_issue_stub(task_spec, workspace_root: Path):
    """A GitHubIssue-shaped identity derived from a task spec (spec mode).

    prepare_issue_workspace needs owner/repo/number to name the clone dir
    and branch; the spec carries all of it — no network fetch required.
    """
    from app.core.issues import GitHubIssue

    owner, _, name = task_spec.repo.partition("/")
    repo_name = name or owner
    # Stable, deterministic issue-number stand-in derived from the pinned
    # commit (never Python's randomized hash(): the clone dir must be
    # reproducible across processes and runs).
    number = int(task_spec.base_commit[:8], 16) % 900000
    return GitHubIssue(
        owner=owner or "spec",
        repo=repo_name,
        number=number,
        title=task_spec.problem_statement[:120],
        body=task_spec.problem_statement,
        labels=(),
        state="spec",
        html_url=f"spec://{task_spec.repo}@{task_spec.base_commit}",
    )


app.add_typer(issues_app, name="issue")


@issues_app.command("view")
def issue_view(
    owner: Annotated[str, typer.Option(help="Repository owner, e.g. 'pandas-dev'.")],
    repo: Annotated[str, typer.Option(help="Repository name, e.g. 'pandas'.")],
    number: Annotated[int, typer.Option(help="Issue number.")],
) -> None:
    """Fetch and display a GitHub issue as the harness sees it."""
    from app.core.issues import fetch_issue

    issue = fetch_issue(owner, repo, number)
    console.print(
        Panel(
            issue.compose_task(),
            title=f"{issue.slug} [{issue.state}]",
            subtitle=", ".join(issue.labels) or "no labels",
        )
    )


@issues_app.command("solve")
def issue_solve(
    owner: Annotated[str, typer.Option(help="Repository owner, e.g. 'pandas-dev'.")],
    repo: Annotated[str, typer.Option(help="Repository name, e.g. 'pandas'.")],
    number: Annotated[int, typer.Option(help="Issue number.")],
    worker: Annotated[
        str,
        typer.Option(
            help=(
                "Worker kind: 'openhands' (default — the harness's own SDK loop, "
                "provider-agnostic via OpenRouter/OpenAI-compatible endpoints), "
                "or a vendor CLI: 'codex' / 'claude' (subscription credit-gated)."
            )
        ),
    ] = "openhands",
    model: Annotated[
        str | None,
        typer.Option(
            help=(
                "LLM for the openhands worker, e.g. 'minimax/minimax-m3:free'. "
                "Defaults to AGENTOPS_OPENROUTER_MODEL from the environment."
            )
        ),
    ] = None,
    workspace_root: Annotated[
        Path,
        typer.Option(help="Directory where the issue workspace is cloned."),
    ] = Path(".agentops/issues"),
    ref: Annotated[
        str, typer.Option(help="Git ref to check out (default HEAD).")
    ] = "HEAD",
    task_spec_file: Annotated[
        Path | None,
        typer.Option(
            "--task-spec",
            help=(
                "SWE-bench-style task-spec JSON file pinning the run: repo, "
                "base_commit, problem_statement, FAIL_TO_PASS, PASS_TO_PASS. "
                "When given, the workspace is cloned at base_commit and the "
                "negative-contract gate proves FAIL_TO_PASS fails BEFORE any "
                "worker dispatch (fail-closed: no reproducible bug, no run)."
            ),
        ),
    ] = None,
    max_attempts: Annotated[
        int, typer.Option(help="Maximum governed retry attempts.")
    ] = 2,
    worker_timeout_seconds: Annotated[
        int, typer.Option(help="Maximum seconds to wait for the worker.")
    ] = 900,
    test_commands: Annotated[
        list[str] | None,
        typer.Option(
            "--test-commands",
            help=(
                "Validation command(s) the harness runs after the worker edits. "
                "Repeatable. Scopes validation to what can honestly run on this "
                "host (e.g. a repo unit-suite subset) instead of failing on "
                "environmental tests (redis, docker, snapshot gates)."
            ),
        ),
    ] = None,
    clone_url: Annotated[
        str | None,
        typer.Option(
            "--clone-url",
            help="Override the clone URL (tests, mirrors, local fixtures).",
        ),
    ] = None,
    goal: Annotated[
        str | None, typer.Option("--goal", help="Intent-graph goal id this run targets.")
    ] = None,
) -> None:
    """Clone the issue's repo, dispatch a governed worker, produce a patch + evidence.

    The flagship demo: a REAL issue from a REAL open-source repository, handed
    to a coding worker inside the governed pipeline (plan → dispatch → enforce
    → validate → retry → report). The output is a branch, a patch, and an
    evidence bundle — never a bare claim.

    The default worker is the harness's own OpenHands SDK loop — a real agent
    loop on any OpenAI-compatible provider (OpenRouter free-tier models work),
    so the flagship is never gated on one vendor's subscription credits. The
    vendor CLIs (codex/claude) are explicit opt-ins for when you have them.
    """
    from app.core.issues import (
        commit_workspace_changes,
        compose_worker_command,
        export_patch,
        fetch_issue,
        prepare_issue_workspace,
    )

    # --task-spec: the deterministic SWE-bench-style contract. When given, the
    # spec (not the gh issue text) IS the run's contract: the clone is pinned
    # to spec.base_commit, and the negative-contract gate must prove the bug
    # reproducible before any worker dispatch. Fail-closed (AO-D01 class):
    # no reproducible bug ⇒ no run, and the budget is not burned.
    task_spec = None
    if task_spec_file is not None:
        from app.schemas.task_spec import SweTaskSpec

        task_spec = SweTaskSpec.from_swebench_instance(
            json.loads(task_spec_file.read_text(encoding="utf-8"))
        )
        ref = task_spec.base_commit  # pin: never clone at a movable HEAD
        console.print(
            f"Task spec: {task_spec.repo} @ {task_spec.base_commit[:12]} "
            f"({len(task_spec.fail_to_pass)} fail_to_pass, "
            f"{len(task_spec.pass_to_pass)} pass_to_pass)"
        )

    if task_spec is not None:
        # Spec mode: the spec IS the identity — repo + base_commit + statement.
        # No gh fetch: the run is reproducible from the spec file alone.
        repo_path, branch = prepare_issue_workspace(
            _spec_issue_stub(task_spec, workspace_root),
            workspace_root,
            ref=task_spec.base_commit,
            clone_url=clone_url,
        )
        console.print(f"Workspace: {repo_path} (branch {branch})")

        from app.core.task_spec_gate import evaluate_negative_contract

        console.print("[dim]Negative-contract gate: proving the bug at base_commit…[/dim]")
        gate = evaluate_negative_contract(task_spec, repo_path)
        if not gate.passed:
            console.print("[red]Negative contract FAILED — run blocked before dispatch:[/red]")
            for reason in gate.reasons:
                console.print(f"  - {reason}")
            raise typer.Exit(code=3)
        console.print(
            f"[green]Negative contract holds: {len(gate.command_results)} "
            "fail_to_pass test(s) fail at base_commit as specified.[/green]"
        )
        task = task_spec.problem_statement
        patch_name = (
            f"{task_spec.repo.replace('/', '-')}-{task_spec.base_commit[:10]}.patch"
        )
        commit_message = (
            f"fix: {task_spec.repo}@{task_spec.base_commit[:12]} (agentops task-spec run)"
        )
    else:
        issue = fetch_issue(owner, repo, number)
        console.print(Panel(f"{issue.slug}: {issue.title}", title="Issue"))
        repo_path, branch = prepare_issue_workspace(
            issue, workspace_root, ref=ref, clone_url=clone_url
        )
        console.print(f"Workspace: {repo_path} (branch {branch})")
        task = issue.compose_task()
        patch_name = f"{issue.repo}-{issue.number}.patch"
        commit_message = f"fix: resolve {issue.slug} (agentops governed run)"

    if worker in ("codex", "claude"):
        worker_command = compose_worker_command(worker, repo_path=repo_path, task=task)
        worker_type = None
        console.print(f"Vendor CLI worker: {worker}")
    elif worker == "openhands":
        worker_command = None
        worker_type = "openhands"
        # The override flows via the environment: _runner_env() copies os.environ
        # (setdefault preserves it), and the runner's load_openhands_config()
        # resolves AGENTOPS_OPENROUTER_MODEL → LLM(model="openrouter/<model>").
        if model:
            os.environ["AGENTOPS_OPENROUTER_MODEL"] = model
        resolved_model = model or settings.openrouter_model
        console.print(f"OpenHands SDK worker · model: {resolved_model}")
    else:
        raise typer.BadParameter(
            f"Unknown worker {worker!r}. Supported: openhands (default), codex, claude."
        )

    record = run_harness(
        repo_path=repo_path,
        task=task,
        storage_path=ISSUE_STORAGE_PATH,
        worker_command=worker_command,
        worker_type=worker_type,
        worker_timeout_seconds=worker_timeout_seconds,
        test_commands=list(test_commands) if test_commands else None,
        max_attempts=max_attempts,
        target_goal_id=goal,
        allow_dirty=True,  # the issue branch IS the workspace; attribution is per-branch
    )

    if task_spec is not None:
        from app.core.task_spec_gate import evaluate_positive_contract

        console.print(
            "[dim]Positive-contract gate: FAIL_TO_PASS must pass and "
            "PASS_TO_PASS must hold on the patched tree…[/dim]"
        )
        positive = evaluate_positive_contract(task_spec, repo_path)
        for cmd in positive.command_results:
            record.execution_logs.append(
                f"positive_contract:{cmd.command} exit={cmd.exit_code}"
            )
        if not positive.passed:
            prior = record.status
            record.status = "failed"
            record.execution_logs.append(
                f"positive_contract:FAILED — verdict folded into record.status "
                f"(worker reported: {prior})"
            )
            for reason in positive.reasons:
                console.print(f"  [red]- {reason}[/red]")
            RunStorage(ISSUE_STORAGE_PATH).save(record)
            console.print(
                "[red]Positive contract FAILED — run marked failed and the "
                f"corrected verdict saved. Evidence: .agentops/runs/{record.run_id}/ "
                "(execution success is not evaluation success, AO-D01-02).[/red]"
            )
            raise typer.Exit(code=4)
        console.print(
            "[green]Positive contract holds: FAIL_TO_PASS pass and PASS_TO_PASS "
            "still pass on the patched tree.[/green]"
        )

    console.print(Panel(record.final_report.markdown, title=f"Run {record.run_id}"))
    console.print(f"status={record.status} attempts={record.attempts} converged={record.converged}")

    if record.changed_files:
        patch_file = export_patch(repo_path, workspace_root / patch_name)
        commit_workspace_changes(repo_path, commit_message)
        console.print(f"Patch: {patch_file}")
    console.print(f"Evidence: .agentops/runs/{record.run_id}/")
