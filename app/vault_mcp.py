"""vault-mcp — MCP server exposing the Obsidian Brain to all workers.

Connects Claude Code, Codex CLI, and Cursor to the Brain via the VaultCodec.
Requires Obsidian Local REST API plugin running at localhost:27123.

Entry point: `agentops-vault-mcp` (registered in pyproject.toml)
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.core.codecs.vault_codec import VaultCodec, VaultCodecError
from app.core.config import settings


def _codec() -> VaultCodec:
    return VaultCodec(base_url=settings.vault_url, api_key=settings.vault_api_key)


def vault_ping() -> dict[str, bool]:
    """Check whether the Obsidian vault is reachable."""
    return {"reachable": _codec().ping()}


def vault_read(path: str) -> dict[str, str]:
    """Read a note from the Brain by vault-relative path.

    Example path: '02-Projects/01-ContextForge/research.md'
    """
    try:
        note = _codec().read(path)
        return {"path": note.path, "content": note.content}
    except VaultCodecError as e:
        return {"error": str(e)}


def vault_write(path: str, content: str) -> dict[str, str]:
    """Create or fully replace a note in the Brain.

    Use for writing new project notes, build logs, or MOC updates.
    """
    try:
        _codec().write(path, content)
        return {"status": "ok", "path": path}
    except VaultCodecError as e:
        return {"error": str(e)}


def vault_append(path: str, content: str) -> dict[str, str]:
    """Append content to an existing Brain note (creates it if absent).

    Use for adding build log entries without overwriting existing content.
    """
    try:
        _codec().append(path, content)
        return {"status": "ok", "path": path}
    except VaultCodecError as e:
        return {"error": str(e)}


def vault_list(folder: str) -> dict[str, list[str]]:
    """List notes inside a Brain folder.

    Example folder: '04-Resources/repos'
    """
    try:
        files = _codec().list_folder(folder)
        return {"folder": folder, "files": files}
    except VaultCodecError as e:
        return {"error": str(e)}


def vault_search(query: str) -> dict[str, list[dict[str, str | float]]]:
    """Full-text search across the entire Brain vault."""
    try:
        results = _codec().search(query)
        return {
            "results": [
                {"filename": r.filename, "score": r.score, "excerpt": r.excerpt}
                for r in results
            ]
        }
    except VaultCodecError as e:
        return {"error": str(e)}


def create_vault_mcp_server() -> FastMCP:
    mcp = FastMCP("vault")
    mcp.tool()(vault_ping)
    mcp.tool()(vault_read)
    mcp.tool()(vault_write)
    mcp.tool()(vault_append)
    mcp.tool()(vault_list)
    mcp.tool()(vault_search)
    return mcp


def main() -> None:
    create_vault_mcp_server().run()


if __name__ == "__main__":
    main()
