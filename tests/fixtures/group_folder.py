"""A project folder of a group, as a team deployment makes it (A-ADR-058).

``group_folder(path)`` gives an existing directory the mode ``2750`` and a
group of the account, so a test of what Archiwista writes in it depends on
neither the umask nor where the tests' temporary directory lies: a parent
with the set-group-ID bit would otherwise give the folder its group and that
bit (E7-12).
"""

import os
from pathlib import Path

GROUP_FOLDER_MODE = 0o2750


def group_folder(path: Path) -> int:
    """Make ``path`` a ``2750`` folder of a group of the account; return the group.

    The group is another group of the account than its own when it has one,
    so the folder's entries being of that group shows they took it from the
    folder, not from the account; else the account's own group.
    """
    own = os.getegid()
    others = sorted(set(os.getgroups()) - {own})
    group = others[0] if others else own
    os.chown(path, -1, group)
    path.chmod(GROUP_FOLDER_MODE)
    return group
