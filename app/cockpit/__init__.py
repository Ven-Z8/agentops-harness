"""AgentOps Cockpit — a local-first observability UI over run artifacts.

The cockpit is *pure projection*: it reads the run records and per-run artifact
bundles the harness already writes, and renders them. It adds no new source of
truth and makes no LLM calls. Mounted onto the existing FastAPI app so a single
``uvicorn app.api:api`` serves both the JSON API and the cockpit at ``/cockpit``.
"""

from app.cockpit.mount import mount_cockpit

__all__ = ["mount_cockpit"]
