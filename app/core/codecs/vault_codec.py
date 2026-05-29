"""VaultCodec — read/write the Obsidian Brain via Local REST API.

Requires the Obsidian Local REST API community plugin running at localhost:27123.
Plugin: https://github.com/coddingtonbear/obsidian-local-rest-api
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

import httpx


@dataclass(frozen=True)
class VaultNote:
    path: str
    content: str


@dataclass(frozen=True)
class VaultSearchResult:
    filename: str
    score: float
    excerpt: str


class VaultCodecError(Exception):
    """Raised when the vault is unreachable or returns an error."""


class VaultCodec:
    """Codec that translates between the harness and the Obsidian Brain.

    All workers call this codec — none talk to the REST API directly.
    """

    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        token = api_key.removeprefix("Bearer ").strip()
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "text/markdown",
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _client(self) -> httpx.Client:
        # verify=False handles the self-signed cert from Obsidian Local REST API HTTPS mode
        return httpx.Client(
            base_url=self._base_url, headers=self._headers, timeout=10.0, verify=False
        )

    def _encode(self, path: str) -> str:
        return quote(path.lstrip("/"), safe="/")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        """Return True if the Obsidian vault is reachable."""
        try:
            with self._client() as c:
                r = c.get("/")
                return r.status_code < 500
        except httpx.ConnectError:
            return False

    def read(self, path: str) -> VaultNote:
        """Read a note by vault-relative path (e.g. '02-Projects/01-ContextForge/MOC.md')."""
        with self._client() as c:
            r = c.get(f"/vault/{self._encode(path)}")
        if r.status_code == 404:
            raise VaultCodecError(f"Note not found: {path}")
        if r.status_code != 200:
            raise VaultCodecError(f"Read failed [{r.status_code}]: {path}")
        return VaultNote(path=path, content=r.text)

    def write(self, path: str, content: str) -> None:
        """Create or fully replace a note."""
        with self._client() as c:
            r = c.put(f"/vault/{self._encode(path)}", content=content)
        if r.status_code not in (200, 204):
            raise VaultCodecError(f"Write failed [{r.status_code}]: {path}")

    def append(self, path: str, content: str) -> None:
        """Append content to an existing note (creates it if absent)."""
        with self._client() as c:
            r = c.post(f"/vault/{self._encode(path)}", content=content)
        if r.status_code not in (200, 204):
            raise VaultCodecError(f"Append failed [{r.status_code}]: {path}")

    def list_folder(self, folder: str) -> list[str]:
        """Return note paths inside a vault folder."""
        folder = folder.rstrip("/") + "/"
        with self._client() as c:
            r = c.get(f"/vault/{self._encode(folder)}")
        if r.status_code == 404:
            return []
        if r.status_code != 200:
            raise VaultCodecError(f"List failed [{r.status_code}]: {folder}")
        data = r.json()
        return data.get("files", [])

    def search(self, query: str, context_length: int = 200) -> list[VaultSearchResult]:
        """Full-text search across the vault."""
        with self._client() as c:
            r = c.post(
                "/search/simple/",
                params={"query": query, "contextLength": context_length},
                headers={**self._headers, "Content-Type": "application/json"},
            )
        if r.status_code != 200:
            raise VaultCodecError(f"Search failed [{r.status_code}]: {query!r}")
        results = r.json()
        return [
            VaultSearchResult(
                filename=item.get("filename", ""),
                score=item.get("score", 0.0),
                excerpt=(
                    item.get("matches", [{}])[0].get("context", "")
                    if item.get("matches")
                    else ""
                ),
            )
            for item in results
        ]
