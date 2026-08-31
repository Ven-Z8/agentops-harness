# Project Control Room

This directory is the shared, vendor-neutral index for agents and humans. Git
owns durable project knowledge and approved roadmap scope; GitHub Issues and
Projects own live execution state.

- [Product boundary](PROJECT.md)
- [Current state](CURRENT.md)
- [Approved 14-day roadmap](roadmap/14-day-plan.md)
- [Offline board snapshot](BOARD.md)
- [Decisions](decisions/README.md)
- [Handoffs](handoffs/README.md)
- [Artifact metadata](artifacts/README.md)
- [Repository code graph](codegraph/summary.md)
- [Record templates](templates/)
- [Approved design](designs/2026-08-30-project-control-room-design.md)
- [Implementation plan](plans/2026-08-30-project-control-room-implementation.md)

Before relying on generated state, run:

```bash
uv run python scripts/project_control.py validate
```
