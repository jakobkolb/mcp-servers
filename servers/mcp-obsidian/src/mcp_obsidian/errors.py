class VaultError(Exception):
    """Base for all vault errors. Always include a human-readable message."""


class VaultPathError(VaultError):
    """Path escapes vault root, is absolute, or is otherwise invalid."""


class NoteNotFoundError(VaultError):
    """The requested note path does not exist."""


class NotANoteError(VaultError):
    """The path exists but is not a .md file."""
