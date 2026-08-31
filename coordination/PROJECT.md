# AgentOps product boundary

AgentOps is a local-first outer control harness for swappable coding workers. It
provides planning, governance, validation, and evidence around a worker's edit
loop; it does not replace or reimplement that worker's tight model/tool loop.

The Project Control Room is a coordination and governance system. It is not a
replacement for Git, GitHub Issues, CI, experiment evidence, or specialist
agent runtimes. Git is authoritative for source code, durable project knowledge,
and approved roadmap identity, outcomes, and scope. GitHub owns live execution
state, assignment, priority, and operational notes.

## Current scope

The approved control-room scope is a universal entry point, strict local
records, structured handoffs and artifact metadata, a deterministic repository
code graph, generated offline snapshots, and a dry-run-first path to GitHub
Projects reconciliation. Missing or invalid required evidence remains
inconclusive and never becomes an inferred pass.

## Explicit limitations

This work does not implement the 14-day product roadmap or change AgentOps
experiment, evaluation, promotion, worker, workspace, permission, or training
runtime behavior. It does not start the experiment kernel, DeepEval integration,
governed training, capability-pack redesign, rebranding, or release work.

In particular, it does not implement a VLM workflow or a VLA provider/simulator
seam. The VLM and VLA entries are later roadmap outcomes marked
`needs-revalidation`; they are not evidence that either capability exists or is
complete today.
