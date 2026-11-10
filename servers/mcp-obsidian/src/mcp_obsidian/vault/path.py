from pathlib import Path

from mcp_obsidian.errors import VaultPathError


def resolve(vault_root: str, relative: str) -> Path:
    """
    Resolve a vault-relative path string to an absolute Path.
    - `relative` must not be absolute or empty
    - After resolution, the result must be inside the vault
    - No component of the resolved path may start with "." (.obsidian/, .trash/,
      .git/, ...). Those hold Obsidian's own settings and plugin code, which the
      agent has no business writing: a plugin's main.js is code that Obsidian runs.
      Checked after resolution, so symlinks into a hidden directory are caught too.
    """
    if not relative or not relative.strip():
        raise VaultPathError("Path must not be empty.")

    path = Path(relative)
    if path.is_absolute():
        raise VaultPathError(f"Path must be vault-relative, not absolute: {relative!r}")

    root = Path(vault_root).resolve()
    full = (root / path).resolve()
    try:
        full.relative_to(root)
    except ValueError as exc:
        raise VaultPathError(f"Path escapes vault root: {relative!r}") from exc

    if any(part.startswith(".") for part in full.relative_to(root).parts):
        raise VaultPathError(f"Hidden paths are not accessible: {relative!r}")

    return full


def to_relative(vault_root: str, absolute: Path) -> str:
    """Convert an absolute path back to a vault-relative string."""
    return str(absolute.relative_to(Path(vault_root).resolve()))
