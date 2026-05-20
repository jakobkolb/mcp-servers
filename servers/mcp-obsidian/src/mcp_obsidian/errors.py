class VaultError(Exception):
    """Base for all vault errors. Always include a human-readable message."""


class VaultPathError(VaultError):
    """Path escapes vault root, is absolute, or is otherwise invalid."""


class NoteNotFoundError(VaultError):
    """The requested note path does not exist."""


class NoteAlreadyExistsError(VaultError):
    """write_note with mode='create' but the note already exists."""


class NotANoteError(VaultError):
    """The path exists but is not a .md file."""


class PatchNoMatchError(VaultError):
    """patch_note: old_string not found in file."""


class PatchAmbiguousError(VaultError):
    """patch_note: old_string matches multiple times and replace_all=False."""


class FrontmatterError(VaultError):
    """YAML parse or serialization error."""


class TaskStateError(VaultError):
    """Task is not in the expected state (e.g. already completed, line out of range)."""
