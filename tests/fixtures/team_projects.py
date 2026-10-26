"""A team's projects in tests: a store, the project directory and three people.

``team_place`` writes a store ``zespol`` whose Kartograf and IMGW directories
are marked stores, the project directory ``nas/projekty``, settings naming
both (in team mode, ``save_team``, unless asked otherwise; with the
``default_project_visibility`` asked) and an index that knows the store.
``team_api`` serves it with the producers' plugins and a job supervisor that
starts no job (``max_jobs=0``: every job waits), after ``add_team`` gave the
state database the administrator anna, kasia and marek, and the group hydro
with kasia.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import imgwtools
import kartograf

from archiwista.auth import LOCAL_OWNER, LOCAL_PRINCIPAL_ID, Principal
from archiwista.auth.authorize import principal_for
from archiwista.config import (
    AppPaths,
    AppSettings,
    ConfigStore,
    DefaultProjectVisibility,
    SettingsService,
    StoreConfig,
)
from archiwista.index import IndexWriter, initialize
from archiwista.jobs import JobSupervisor
from archiwista.sources.registry import load_registry
from archiwista.state import StateStore
from tests.fixtures.api_session import Api, Caller, running_api
from tests.fixtures.team_server import save_team

STORE = "zespol"
MANIFEST = "kartograf-project.json"
ADMIN = "anna"
OWNER = "kasia"
OTHER = "marek"
GROUP = "hydro"


@dataclass(frozen=True)
class TeamPlace:
    """An installation and the directories of its share.

    Attributes
    ----------
    paths : AppPaths
        The settings, the index and the state database.
    projects : Path
        The project directory of the settings.
    imgw : Path
        The store's IMGW directory (a marked IMGW store).
    """

    paths: AppPaths
    projects: Path
    imgw: Path

    def body(self, name: str) -> dict[str, str]:
        """Return the body of ``POST /projects`` of a Kartograf project ``name``."""
        directory = self.projects / name
        return {"producer": "kartograf", "path": str(directory), "store": STORE}


@dataclass(frozen=True)
class TeamApi:
    """The served place: the application and its job supervisor."""

    api: Api
    jobs: JobSupervisor

    @property
    def state(self) -> StateStore:
        """The state database of the server."""
        return self.api.state

    def caller(self, account: str, *, agent: bool = False) -> Caller:
        """Open a session of an account (``local``: the computer's owner).

        With ``agent`` the session is an agent's, from a token the account
        issued.
        """
        if account == LOCAL_PRINCIPAL_ID:
            principal = LOCAL_OWNER
        else:
            principal = person(self.state, account)
        return self.api.session(principal, token="agent" if agent else "startup")


def team_place(
    tmp_path: Path,
    *,
    team: bool = True,
    visibility: DefaultProjectVisibility = "public",
) -> TeamPlace:
    """Write the store, the project directory and the settings (team mode)."""
    share = tmp_path / "nas"
    kartograf.init_store(share / "kartograf")
    imgwtools.init_store(share / "imgw")
    projects = share / "projekty"
    projects.mkdir()
    paths = AppPaths(
        config_file=tmp_path / "config" / "config.toml", data_dir=tmp_path / "data"
    )
    store = StoreConfig(
        id=STORE,
        name="Zespół",
        kartograf=share / "kartograf",
        imgw=share / "imgw",
        kind="share",
    )
    settings = AppSettings(
        stores=(store,),
        project_dirs=(projects,),
        default_project_visibility=visibility,
    )
    if team:
        save_team(paths, settings)
    else:
        ConfigStore(paths.config_file).save(settings)
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({STORE: store.roots()})
    return TeamPlace(paths, projects, share / "imgw")


@contextmanager
def team_api(place: TeamPlace) -> Iterator[TeamApi]:
    """Serve the place with the plugins and jobs that wait; add the team."""
    registry = load_registry(cache_dir=place.paths.cache_dir)
    settings = SettingsService(ConfigStore(place.paths.config_file), registry)
    with (
        JobSupervisor(place.paths, settings, max_jobs=0) as jobs,
        running_api(place.paths, registry, jobs=jobs) as api,
    ):
        add_team(api.state)
        yield TeamApi(api, jobs)


def add_team(state: StateStore) -> None:
    """Create anna (administrator), kasia and marek, and hydro with kasia."""
    state.add_user(ADMIN, name="Anna Nowak", roles=["admin"], actor=LOCAL_OWNER)
    state.add_user(OWNER, name="Kasia Wrona", actor=LOCAL_OWNER)
    state.add_user(OTHER, name="Marek Lis", actor=LOCAL_OWNER)
    state.add_group(GROUP, name="Dział hydrologii", members=(OWNER,), actor=LOCAL_OWNER)


def person(state: StateStore, account: str) -> Principal:
    """Return the principal of an enabled account, with its roles and groups."""
    found = principal_for(state, account)
    assert found is not None
    return found
