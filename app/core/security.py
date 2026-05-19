from pathlib import PurePosixPath

SENSITIVE_FILE_NAMES = {
    ".env",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}

SENSITIVE_PREFIXES = (
    ".env.",
    "secrets.",
    "credentials.",
)

SENSITIVE_FOLDERS = {
    "auth",
    "security",
    "payment",
    "payments",
}

BLOCKED_COMMAND_FRAGMENTS = (
    "rm -rf",
    "git push --force",
    "git reset --hard",
    "sudo ",
)


def normalize_repo_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def is_sensitive_path(path: str) -> bool:
    normalized = normalize_repo_path(path)
    pure_path = PurePosixPath(normalized)
    name = pure_path.name.lower()
    parts = {part.lower() for part in pure_path.parts}

    if name in SENSITIVE_FILE_NAMES:
        return True
    if any(name.startswith(prefix) for prefix in SENSITIVE_PREFIXES):
        return True
    if SENSITIVE_FOLDERS.intersection(parts):
        return True
    if "private" in name and "key" in name:
        return True
    return name.endswith(".pem") or name.endswith(".key")


def validate_safe_command(command: str) -> None:
    lowered = command.lower()
    for fragment in BLOCKED_COMMAND_FRAGMENTS:
        if fragment in lowered:
            raise ValueError(f"Blocked potentially destructive command: {command}")
