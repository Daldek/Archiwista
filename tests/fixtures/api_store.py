"""A generated Kartograf store, scanned into the index and served by the API."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from archiwista.auth import LOCAL_OWNER
from archiwista.config import AppSettings, ConfigStore, StoreConfig
from archiwista.index import IndexWriter, initialize, scan_store
from archiwista.sources.registry import SourceRegistry, load_registry
from tests.fixtures.api_session import Api, Caller, running_api
from tests.fixtures.local_server import local_paths
from tests.fixtures.make_store import StoreManifest, make_store

STORE = "zespol"
ALIAS = "Z:\\"


@dataclass(frozen=True)
class ServedStore:
    """The API over a scanned store, with the local owner's session."""

    api: Api
    store: StoreManifest
    registry: SourceRegistry
    owner: Caller


def store_settings(store: StoreManifest) -> AppSettings:
    """Return settings with the store (aliased as ``Z:``) and its projects."""
    config = StoreConfig(
        id=STORE,
        name="Zespół",
        kartograf=store.root,
        kind="local",
        path_aliases={f"{store.output_dir}/": ALIAS},
    )
    return AppSettings(stores=(config,), project_dirs=(store.projects_dir,))


@contextmanager
def served_store(
    tmp_path: Path,
    *,
    slots: int = 24,
    seed: int = 7,
    before_scan: Callable[[StoreManifest], object] | None = None,
) -> Iterator[ServedStore]:
    """Generate a store, scan it fully into a fresh index and serve the API."""
    store = make_store(tmp_path / "store", slots=slots, seed=seed)
    paths = local_paths(tmp_path)
    settings = store_settings(store)
    ConfigStore(paths.config_file).save(settings)
    registry = load_registry(cache_dir=paths.cache_dir)
    if before_scan is not None:
        before_scan(store)
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({STORE: {"kartograf": store.root}})
        adapter = registry.adapter("kartograf")
        scan_store(adapter, writer, settings, STORE, mode="full")
        scan_store(adapter, writer, settings, STORE, mode="incremental")
    with running_api(paths, registry) as api:
        yield ServedStore(api, store, registry, api.session(LOCAL_OWNER))
