"""Which projects a principal sees: ``ProjectVisibility`` and project access keys.

A project's access entry in the state database (owner, visibility, people
and groups) is keyed by the project directory after ``realpath``, not by an
index identifier, so an index rebuild keeps it and every path that reaches
the directory through symbolic links shares it (A-ADR-029). The index
records the same key for each project it discovers (``access_key``), which
lets its queries filter projects and pins with one ``ProjectVisibility``.
"""

import os
from dataclasses import dataclass


def access_key(directory: str | os.PathLike[str]) -> str:
    r"""Return a project's key in the state database.

    Parameters
    ----------
    directory : str or os.PathLike[str]
        The project directory, as discovered or as typed.

    Returns
    -------
    str
        The directory with symbolic links resolved (``os.path.realpath``) and,
        on Windows, its case folded (``os.path.normcase``).
    """
    return os.path.normcase(os.path.realpath(directory))


@dataclass(frozen=True, slots=True)
class ProjectVisibility:
    """The projects one principal may see, by access key.

    An administrator sees ``everything``. Otherwise a project with an access
    entry is visible when its key is in ``granted`` and hidden when it is in
    ``denied``; a project without an entry follows ``unlisted``
    (``default_project_visibility``). ``Authorizer.visible_projects`` builds
    it; index queries and services filter projects and pins with it.

    Parameters
    ----------
    everything : bool
        Every project is visible.
    granted : frozenset[str]
        Keys of projects whose access entry admits the principal.
    denied : frozenset[str]
        Keys of projects whose access entry does not admit the principal.
    unlisted : bool
        Whether projects without an access entry are visible.
    """

    everything: bool = False
    granted: frozenset[str] = frozenset()
    denied: frozenset[str] = frozenset()
    unlisted: bool = False

    def sees(self, key: str) -> bool:
        """Return whether the project with access key ``key`` is visible."""
        if self.everything or key in self.granted:
            return True
        return self.unlisted and key not in self.denied


ALL_PROJECTS = ProjectVisibility(everything=True)
