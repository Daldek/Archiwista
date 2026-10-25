"""Own data of projects over HTTP: two projects' data folders served (step 9).

``own_data_api`` generates a store with ``make_store`` (its project
``projekt-01`` pins versions of it), writes the data folder of that project
with the requested families (``make_own_folder`` in ``<project>/dane``), adds a
second project ``odra`` with a data folder of its own, scans both folders as
an ``own_scan`` does (``scan_own_data``) and serves the application with
render processes, a job supervisor with the real worker and the four people
of ``tests.fixtures.permissions``; who sees which project is up to the test
(``share``).
"""

from collections.abc import Collection, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from archiwista.auth import ALL_PROJECTS, access_key
from archiwista.config import AppPaths, ConfigStore
from archiwista.index import (
    IndexQueries,
    IndexWriter,
    ManifestStamp,
    own_file_id,
)
from archiwista.jobs import JobRecord, JobSupervisor
from archiwista.owndata.scan import OwnScanSummary, scan_own_data
from archiwista.sources import ProjectInfo
from archiwista.sources.registry import load_registry
from tests.fixtures.api_session import Api, Caller
from tests.fixtures.own_data import OwnFolderManifest, make_own_folder
from tests.fixtures.permissions import Who, add_people, principal
from tests.fixtures.preview_api import PreviewApi, scanned_store, serve_previews

FIRST = "projekt-01"
SECOND = "odra"
DATA_DIR = "dane"


@dataclass(frozen=True)
class OwnProject:
    """A project with a data folder: its key, directory and folder's files."""

    key: str
    directory: Path
    folder: OwnFolderManifest

    @property
    def access_key(self) -> str:
        """Key of the project's access entry (its directory after ``realpath``)."""
        return access_key(self.directory)

    @property
    def root(self) -> Path:
        """The data folder."""
        return self.folder.root

    def ref(self, path: str) -> str:
        """Return the ``ref`` of a working file (``file:<project>:<path>``)."""
        return f"file:{self.key}:{path}"

    def url(self, path: str, route: str = "") -> str:
        """Return the address of a file, or of one of its routes, below ``/api/v1``."""
        base = f"/projects/{self.key}/files/{own_file_id(path)}"
        return f"{base}/{route}" if route else base

    def snapshot_url(self, path: str, label: str, route: str = "preview") -> str:
        """Return the address of a route of a file's snapshot, below ``/api/v1``."""
        return self.url(path, f"snapshots/{label}/{route}")


@dataclass(frozen=True)
class OwnDataApi:
    """The served store, its two projects with data folders, and the people."""

    previews: PreviewApi
    first: OwnProject
    second: OwnProject

    @property
    def api(self) -> Api:
        """The running application."""
        return self.previews.api

    @property
    def owner(self) -> Caller:
        """A session of the computer's owner (local mode)."""
        return self.previews.owner

    @property
    def jobs(self) -> JobSupervisor:
        """The server's job supervisor."""
        return self.previews.jobs

    @property
    def paths(self) -> AppPaths:
        """The index, state, settings and caches of the server."""
        return self.api.paths

    def caller(self, who: Who) -> Caller:
        """Open a session of one of the four people."""
        return self.api.session(principal(self.api.state, who))

    def get(self, caller: Caller, url: str, *, etag: str | None = None) -> Any:
        """``GET`` an address as ``caller`` (from an answer: ``/api/v1…``)."""
        path = url.removeprefix("/api/v1")
        headers = {"cookie": f"archiwista_session={caller.session_id}"}
        headers["x-archiwista-csrf"] = caller.csrf
        if etag is not None:
            headers["if-none-match"] = etag
        response: httpx.Response = caller.client.get(f"/api/v1{path}", headers=headers)
        return response

    def scan(self) -> OwnScanSummary:
        """Scan every project's data folder into the index, as ``own_scan`` does."""
        return scan_own(self.paths)

    def wait(self, job_id: str) -> JobRecord:
        """Wait for a job to end and return it."""
        return self.previews.wait(job_id)


def scan_own(paths: AppPaths) -> OwnScanSummary:
    """Scan the data folders of every indexed project with Kartograf's operations."""
    settings = ConfigStore(paths.config_file).load()
    adapter = load_registry(cache_dir=paths.cache_dir).adapter("kartograf")
    with (
        IndexWriter(paths.index_file) as writer,
        IndexQueries(paths.index_file) as queries,
    ):
        known = queries.projects(visible=ALL_PROJECTS)
        return scan_own_data(
            writer,
            known,
            known_projects=known,
            settings=settings,
            paths=paths,
            transformer=adapter.transformer,  # type: ignore[attr-defined]
            prune=True,
        )


@contextmanager
def own_data_api(
    tmp_path: Path,
    *,
    first: Collection[str] = ("gpkg_layers", "shp_full", "tif_2180"),
    second: Collection[str] = ("tif_2180",),
    workers: int = 2,
) -> Iterator[OwnDataApi]:
    """Serve a store and two projects with scanned data folders (see the module).

    Parameters
    ----------
    tmp_path : Path
        Empty directory for the store, the projects and the server's data.
    first, second : collection of str
        Families (``tests.fixtures.own_data.OwnFamily``) of the data folders
        of ``projekt-01`` and ``odra``.
    workers : int, default 2
        Render processes.
    """
    store, paths = scanned_store(tmp_path)
    first_dir = store.base / store.project(FIRST).path
    first_folder = make_own_folder(first_dir / DATA_DIR, families=first)
    second_dir = tmp_path / "projekty" / SECOND
    second_dir.mkdir(parents=True)
    second_folder = make_own_folder(second_dir / DATA_DIR, families=second)
    with IndexWriter(paths.index_file) as writer:
        info = ProjectInfo("kartograf", str(store.root), second_dir, "Odra")
        key = writer.write_project(info, store=None, stamp=ManifestStamp(None, None))
    assert key == SECOND, key
    scan_own(paths)
    with serve_previews(store, paths, workers=workers) as served:
        add_people(served.api.state)
        yield OwnDataApi(
            served,
            OwnProject(FIRST, first_dir, first_folder),
            OwnProject(SECOND, second_dir, second_folder),
        )
