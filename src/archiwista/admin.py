"""``archiwista users``, ``groups``, ``share`` and ``state``: permission administration.

The commands act as the owner of the local installation (``LOCAL_OWNER``,
roles ``admin`` and ``store_writer``) through the same services as the HTTP
routes of ``archiwista/api/admin.py``, so ``--json`` prints exactly the
models of those routes and every change lands in the permission log
(A-ADR-029). A refused action exits with the registry's exit code and ends
standard error with the ``archiwista-error/1`` document, the Polish text
before it (ERR-4). ``state export`` and ``state import`` back up and restore the state
database (``archiwista-state/1``, into an empty database only).
"""

import argparse
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from pydantic import BaseModel

from archiwista.api.admin import Group, GroupList, ProjectAccess, User, UserList
from archiwista.auth import LOCAL_OWNER
from archiwista.auth.authorize import Authorizer
from archiwista.config import (
    AppPaths,
    ConfigStore,
    SettingsValidationError,
    write_text_atomic,
)
from archiwista.error_document import (
    describe,
    exception_problem,
    fail,
    refuse,
)
from archiwista.errors import ArchiwistaError, StateError
from archiwista.index import IndexQueries, IndexUnsupportedError
from archiwista.messages import message, with_detail
from archiwista.services import access as access_service
from archiwista.state import (
    ROLES,
    VISIBILITIES,
    StateStore,
    dump_state,
    export_state,
    import_state,
)

ADMIN_COMMANDS = frozenset({"users", "groups", "share", "state"})

type _Commands = argparse._SubParsersAction[argparse.ArgumentParser]


@dataclass(frozen=True, slots=True)
class _Output:
    """What a command prints: the API model with ``--json``, else Polish text."""

    model: BaseModel | None
    text: str


type _Command = Callable[[argparse.Namespace, Authorizer], _Output]


def add_admin_commands(commands: _Commands) -> None:
    """Add ``users``, ``groups``, ``share`` and ``state`` to ``archiwista``.

    Parameters
    ----------
    commands : argparse._SubParsersAction
        Subcommands of the ``archiwista`` parser.
    """
    users = _subcommands(commands, "users", message("cli.users_help"))
    _parser(users, "list", message("cli.users_list_help"))
    add = _parser(users, "add", message("cli.users_add_help"))
    add.add_argument("id", metavar="ID", help=message("cli.user_id_help"))
    add.add_argument("--name", help=message("cli.name_help"))
    add.add_argument(
        "--role",
        dest="roles",
        action="extend",
        nargs="+",
        choices=ROLES,
        default=[],
        help=message("cli.role_help"),
    )
    roles = _parser(users, "roles", message("cli.users_roles_help"))
    roles.add_argument("id", metavar="ID", help=message("cli.user_id_help"))
    roles.add_argument(
        "roles",
        metavar=message("metavar.role"),
        nargs="*",
        choices=ROLES,
        help=message("cli.role_help"),
    )
    remove = _parser(users, "remove", message("cli.users_remove_help"))
    remove.add_argument("id", metavar="ID", help=message("cli.user_id_help"))

    groups = _subcommands(commands, "groups", message("cli.groups_help"))
    _parser(groups, "list", message("cli.groups_list_help"))
    add = _parser(groups, "add", message("cli.groups_add_help"))
    add.add_argument("id", metavar="ID", help=message("cli.group_id_help"))
    add.add_argument("--name", help=message("cli.name_help"))
    add.add_argument(
        "--member",
        dest="members",
        action="extend",
        nargs="+",
        default=[],
        metavar=message("metavar.person"),
        help=message("cli.member_help"),
    )
    members = _parser(groups, "members", message("cli.groups_members_help"))
    members.add_argument("id", metavar="ID", help=message("cli.group_id_help"))
    members.add_argument(
        "members",
        metavar=message("metavar.person"),
        nargs="*",
        help=message("cli.member_help"),
    )
    remove = _parser(groups, "remove", message("cli.groups_remove_help"))
    remove.add_argument("id", metavar="ID", help=message("cli.group_id_help"))

    share = commands.add_parser(
        "share", help=message("cli.share_help"), description=message("cli.share_help")
    )
    share.add_argument(
        "project", metavar=message("metavar.project"), help=message("cli.project_help")
    )
    share.add_argument(
        "--visibility", choices=VISIBILITIES, help=message("cli.visibility_help")
    )
    share.add_argument(
        "--user",
        dest="users",
        action="extend",
        nargs="+",
        default=[],
        metavar="ID",
        help=message("cli.share_user_help"),
    )
    share.add_argument(
        "--group",
        dest="groups",
        action="extend",
        nargs="+",
        default=[],
        metavar="ID",
        help=message("cli.share_group_help"),
    )
    share.add_argument("--owner", metavar="ID", help=message("cli.owner_help"))
    _json_option(share)

    state = _subcommands(commands, "state", message("cli.state_help"))
    export = _parser(state, "export", message("cli.state_export_help"), with_json=False)
    export.add_argument(
        "--output",
        type=Path,
        metavar=message("metavar.file"),
        help=message("cli.state_output_help"),
    )
    restore = _parser(
        state, "import", message("cli.state_import_help"), with_json=False
    )
    restore.add_argument(
        "file",
        type=Path,
        metavar=message("metavar.file"),
        help=message("cli.state_file_help"),
    )


def admin_main(
    args: argparse.Namespace, paths: AppPaths, out: TextIO, err: TextIO
) -> int:
    """Run one of the commands added by ``add_admin_commands``.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments (``command`` in ``ADMIN_COMMANDS``).
    paths : AppPaths
        Configuration file, local index and state database.
    out, err : TextIO
        Results (JSON with ``--json``) and Polish explanations.

    Returns
    -------
    int
        ``0`` on success, ``1`` when the action is refused or fails, ``2``
        for options that do not go together.
    """
    as_json = bool(getattr(args, "json", False))
    try:
        if args.command == "state":
            return _state(args, paths, out, err)
        settings = ConfigStore(paths.config_file).load()
        authorizer = Authorizer(StateStore(paths.state_file), lambda: settings)
        if args.command == "share":
            if args.visibility is None and (args.users or args.groups or args.owner):
                return fail(
                    err,
                    "validation_error",
                    message("cli.share_needs_visibility"),
                    reason="share_needs_visibility",
                )
            output = _share(args, authorizer, paths)
        else:
            commands = _USERS if args.command == "users" else _GROUPS
            output = commands[args.action](args, authorizer)
    except (SettingsValidationError, IndexUnsupportedError, StateError) as error:
        return refuse(
            exception_problem(
                error, with_detail(message("cli.admin_failed"), str(error))
            ),
            err,
        )
    except ArchiwistaError as error:
        return refuse(describe(error), err)
    if as_json:
        if output.model is not None:
            out.write(output.model.model_dump_json() + "\n")
    else:
        out.write(output.text + "\n")
    return 0


# Accounts and groups.


def _list_users(args: argparse.Namespace, authorizer: Authorizer) -> _Output:
    users = UserList(
        items=[
            User.of(user) for user in access_service.list_users(authorizer, LOCAL_OWNER)
        ]
    )
    lines = [_user_text(user) for user in users.items]
    return _Output(users, "\n".join(lines) or message("cli.no_users"))


def _add_user(args: argparse.Namespace, authorizer: Authorizer) -> _Output:
    user = User.of(
        access_service.add_user(
            authorizer, LOCAL_OWNER, args.id, name=args.name, roles=args.roles
        )
    )
    return _Output(user, _user_text(user))


def _set_roles(args: argparse.Namespace, authorizer: Authorizer) -> _Output:
    user = User.of(
        access_service.update_user(authorizer, LOCAL_OWNER, args.id, roles=args.roles)
    )
    return _Output(user, _user_text(user))


def _remove_user(args: argparse.Namespace, authorizer: Authorizer) -> _Output:
    access_service.remove_user(authorizer, LOCAL_OWNER, args.id)
    return _Output(None, message("cli.user_removed", id=args.id))


def _list_groups(args: argparse.Namespace, authorizer: Authorizer) -> _Output:
    groups = GroupList(
        items=[
            Group.of(group)
            for group in access_service.list_groups(authorizer, LOCAL_OWNER)
        ]
    )
    lines = [_group_text(group) for group in groups.items]
    return _Output(groups, "\n".join(lines) or message("cli.no_groups"))


def _add_group(args: argparse.Namespace, authorizer: Authorizer) -> _Output:
    group = Group.of(
        access_service.add_group(
            authorizer, LOCAL_OWNER, args.id, name=args.name, members=args.members
        )
    )
    return _Output(group, _group_text(group))


def _set_members(args: argparse.Namespace, authorizer: Authorizer) -> _Output:
    group = Group.of(
        access_service.set_group_members(authorizer, LOCAL_OWNER, args.id, args.members)
    )
    return _Output(group, _group_text(group))


def _remove_group(args: argparse.Namespace, authorizer: Authorizer) -> _Output:
    access_service.remove_group(authorizer, LOCAL_OWNER, args.id)
    return _Output(None, message("cli.group_removed", id=args.id))


_USERS: dict[str, _Command] = {
    "list": _list_users,
    "add": _add_user,
    "roles": _set_roles,
    "remove": _remove_user,
}
_GROUPS: dict[str, _Command] = {
    "list": _list_groups,
    "add": _add_group,
    "members": _set_members,
    "remove": _remove_group,
}


# Project access and backups.


def _share(
    args: argparse.Namespace, authorizer: Authorizer, paths: AppPaths
) -> _Output:
    with IndexQueries(paths.index_file) as queries:
        if args.visibility is None:
            access = access_service.project_access(
                authorizer, queries, LOCAL_OWNER, args.project
            )
        else:
            access = access_service.share_project(
                authorizer,
                queries,
                LOCAL_OWNER,
                args.project,
                visibility=args.visibility,
                users=args.users,
                groups=args.groups,
                owner=args.owner,
            )
    model = ProjectAccess.of(access)
    listed = model.users if model.visibility == "users" else model.groups
    text = message(
        "cli.access_line",
        project=model.project,
        visibility=message(f"visibility.{model.visibility}"),
        entries=f": {_listing(listed)}" if listed else "",
        owner=model.owner or message("cli.none"),
    )
    return _Output(
        model, text + ("" if model.explicit else message("cli.access_default"))
    )


def _state(args: argparse.Namespace, paths: AppPaths, out: TextIO, err: TextIO) -> int:
    store = StateStore(paths.state_file)
    if args.action == "export":
        text = dump_state(export_state(store))
        if args.output is None:
            out.write(text)
        else:
            write_text_atomic(args.output, text)
            err.write(message("cli.state_exported", path=args.output) + "\n")
        return 0
    try:
        data = args.file.read_bytes()
    except OSError as error:
        detail = error.strerror or str(error)
        missing = isinstance(error, FileNotFoundError)
        raise StateError(
            message("cli.state_unreadable", path=args.file, detail=detail),
            code="not_found" if missing else "io_error",
            reason="backup_missing" if missing else "backup_unreadable",
        ) from error
    restored = import_state(store, data)
    err.write(
        message(
            "cli.state_imported",
            users=len(restored.users),
            groups=len(restored.groups),
            projects=len(restored.projects),
            changes=len(restored.changes),
        )
        + "\n"
    )
    return 0


# Text.


def _user_text(user: User) -> str:
    text = message(
        "cli.user_line",
        id=user.id,
        name=user.name,
        roles=_listing(message(f"role.{role}") for role in user.roles),
        groups=_listing(user.groups),
    )
    return text + (message("cli.user_disabled") if user.disabled else "")


def _group_text(group: Group) -> str:
    return message(
        "cli.group_line", id=group.id, name=group.name, members=_listing(group.members)
    )


def _listing(values: Iterable[str]) -> str:
    return ", ".join(values) or message("cli.none")


def _json_line(data: dict[str, object]) -> str:
    return json.dumps(data, ensure_ascii=False) + "\n"


# Parsers.


def _subcommands(commands: _Commands, name: str, text: str) -> _Commands:
    parser = commands.add_parser(name, help=text, description=text)
    return parser.add_subparsers(
        dest="action", required=True, metavar=message("metavar.action")
    )


def _parser(
    commands: _Commands, name: str, text: str, *, with_json: bool = True
) -> argparse.ArgumentParser:
    parser = commands.add_parser(name, help=text, description=text)
    if with_json:
        _json_option(parser)
    return parser


def _json_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help=message("cli.json_help"))
