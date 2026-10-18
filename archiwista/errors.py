"""Errors shared by producer adapters and application services."""


class ArchiwistaError(Exception):
    """Base error for Archiwista operations."""


class SourceUnavailableError(ArchiwistaError):
    """Producer package or configured store cannot be reached."""


class SourceIncompatibleError(ArchiwistaError):
    """Producer version or store schema is unsupported."""


class PathOutsideRootError(ArchiwistaError):
    """A requested path escapes its configured store or project root."""


class SnapshotError(ArchiwistaError):
    """An own-data snapshot could not be made consistently."""
