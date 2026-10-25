"""The preview cache (plan v0.2, decision 3; contract "Pamięć").

Objects are real files under ``tmp_path``. A test that orders uses injects
its clock and moves it past ``TOUCH_INTERVAL_S``, so that hits are written.
Other processes are real ones (``python -c`` with the repository on
``PYTHONPATH``): they open a new cache together, put and read at the same
time, evict right after this process's hit, or end while holding a pin.
``test_same_content_rendered_once`` serves a generated store with real render
processes (``tests.fixtures.preview_api``).
"""

import hashlib
import json
import os
import random
import subprocess
import sys
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path

import pytest

from archiwista.previews import cache as preview_cache
from archiwista.previews.cache import (
    CACHE_FILE,
    COG_NAME,
    EVICT_TO,
    INCOMING_DIR,
    INFO_NAME,
    OBJECTS_DIR,
    RENDERER_VERSIONS,
    TOUCH_INTERVAL_S,
    CacheKey,
    CacheUsage,
    PreviewCache,
    cache_key,
    composite_key,
    tile_name,
)
from archiwista.previews.compose import layer_thumbnail_target
from archiwista.previews.renderers.raster import probe_raster
from archiwista.previews.types import Extent, PreviewSource, RendererName
from archiwista.sandbox import process_owner
from tests.fixtures import store_files
from tests.fixtures.make_store import StoreManifest
from tests.fixtures.preview_api import (
    PreviewApi,
    center_tile_url,
    entry_of,
    scanned_store,
    serve_previews,
    version_url,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CHILD_TIMEOUT_S = 60.0
# 1 MB as in SPEC: 1 000 000 bytes.
MB = 1_000_000
TILE = tile_name("gray", 12, 2275, 1388)
# One of several processes sharing a cache with a small limit: it opens the
# cache, says "ready", waits for a line on its standard input (all start
# together), then puts (bytes and finished files) and reads (get and open).
# Every file carries its length and SHA-256, so a partial read shows.
SHARING = """
import hashlib, json, random, sys
from pathlib import Path
from archiwista.previews.cache import COG_NAME, RENDERER_VERSIONS
from archiwista.previews.cache import CacheKey, PreviewCache

root, limit, seed = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
rng = random.Random(seed)
version = RENDERER_VERSIONS["raster"]
contents = [hashlib.sha256(bytes([n])).hexdigest() for n in range(6)]
keys = [CacheKey(content, "raster", version) for content in contents]
names = ["info.json", "thumb-gray-256.png", "tiles/gray/3/4/2.png", COG_NAME]

def blob():
    body = rng.randbytes(rng.randrange(1, 40_000))
    return len(body).to_bytes(8, "big") + hashlib.sha256(body).digest() + body

def whole(data):
    body = data[40:]
    return int.from_bytes(data[:8], "big") == len(body) and (
        hashlib.sha256(body).digest() == data[8:40]
    )

counts = {"puts": 0, "hits": 0, "misses": 0, "damaged": 0, "over_limit": 0}
with PreviewCache(root, limit_bytes=limit) as cache:
    print("ready", flush=True)
    sys.stdin.readline()
    for _ in range(150):
        key, name, action = rng.choice(keys), rng.choice(names), rng.random()
        if action < 0.45:
            if action < 0.3:
                cache.put(key, name, blob())
            else:
                staged = cache.incoming_dir() / "build.part"
                staged.write_bytes(blob())
                cache.put(key, name, staged)
            counts["puts"] += 1
            counts["over_limit"] += cache.usage().used_bytes > limit
            continue
        if action < 0.8:
            data = cache.get(key, name)
        else:
            handle = cache.open(key, name)
            data = None if handle is None else handle.read()
            if handle is not None:
                handle.close()
        if data is None:
            counts["misses"] += 1
        else:
            counts["hits"] += 1
            counts["damaged"] += not whole(data)
print(json.dumps(counts))
"""
# Another process evicting everything it may (limit 0); prints bytes freed.
EVICTING = """
import sys
from pathlib import Path
from archiwista.previews.cache import PreviewCache

with PreviewCache(Path(sys.argv[1]), limit_bytes=0) as cache:
    print(cache.evict())
"""
# A build killed while its object is pinned: it never unpins.
CRASHING = """
import os, sys
from pathlib import Path
from archiwista.previews.cache import RENDERER_VERSIONS, CacheKey, PreviewCache

cache = PreviewCache(Path(sys.argv[1]), limit_bytes=int(sys.argv[2]))
cache.pin(CacheKey(sys.argv[3], "raster", RENDERER_VERSIONS["raster"]))
os._exit(0)
"""
# Processes opening new caches together: before each open every one says
# "ready" and waits for a line on its standard input, so that all of them
# open the same new cache at once; one cache per argument.
OPENING = """
import sys
from pathlib import Path
from archiwista.previews.cache import PreviewCache

for root in sys.argv[1:]:
    print("ready", flush=True)
    sys.stdin.readline()
    with PreviewCache(Path(root), limit_bytes=1_000_000):
        pass
"""


class Clock:
    """A clock the test moves: seconds since the epoch, as ``time.time``."""

    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        """Return the time the test set."""
        return self.now

    def advance(self, seconds: float) -> None:
        """Move the time on."""
        self.now += seconds


def _key(seed: str, renderer: RendererName = "raster") -> CacheKey:
    content = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return CacheKey(content, renderer, RENDERER_VERSIONS[renderer])


def _blob(size: int, seed: str) -> bytes:
    """Return ``size`` bytes, others for every seed."""
    block = hashlib.sha256(seed.encode("utf-8")).digest()
    return (block * (size // len(block) + 1))[:size]


def _source(tmp_path: Path, name: str, content: str) -> PreviewSource:
    return PreviewSource(
        ref=f"version:zespol:{name}",
        content_key=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        paths=(tmp_path / name,),
    )


def _child_env() -> dict[str, str]:
    """Return the environment of a child importing the repository's code."""
    paths = [str(REPO_ROOT), os.environ.get("PYTHONPATH", "")]
    return {**os.environ, "PYTHONPATH": os.pathsep.join(path for path in paths if path)}


def _python(script: str, *args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", script, *(str(arg) for arg in args)],
        env=_child_env(),
        capture_output=True,
        text=True,
        timeout=CHILD_TIMEOUT_S,
        check=False,
    )


def _spawn(stack: ExitStack, script: str, *args: object) -> subprocess.Popen[str]:
    """Start a child with pipes; leaving ``stack`` kills it, so a hang fails."""
    child = stack.enter_context(
        subprocess.Popen(
            [sys.executable, "-c", script, *(str(arg) for arg in args)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=_child_env(),
        )
    )
    stack.callback(child.kill)
    return child


def _start_together(children: list[subprocess.Popen[str]]) -> bool:
    """Wait for "ready" from every child, then give each its line to go on.

    Returns ``False``, writing nothing, when a child ended instead: its return
    code and standard error say why, where a write would raise
    ``BrokenPipeError``.
    """
    lines = []
    for child in children:
        assert child.stdout is not None
        lines.append(child.stdout.readline())
    if lines != ["ready\n"] * len(children):
        return False
    for child in children:
        assert child.stdin is not None
        child.stdin.write("go\n")
        child.stdin.flush()
    return True


def _on_disk(root: Path) -> tuple[int, int]:
    """Return the bytes of the objects' files on the disk and the objects."""
    objects = root / OBJECTS_DIR
    sizes: dict[tuple[str, ...], int] = {}
    for path in objects.rglob("*"):
        if path.is_file():
            owner = path.relative_to(objects).parts[:3]
            sizes[owner] = sizes.get(owner, 0) + path.stat().st_size
    return sum(sizes.values()), len(sizes)


def test_cache_limit_evicts_least_recently_used(tmp_path: Path) -> None:
    """Over the limit the least recently used objects go, down to 90 % of it.

    A hit is a use: the object read last survives an object written after
    it but not read since.
    """
    # Arrange
    clock = Clock()
    read, unread, newer, newest = (
        _key(seed) for seed in ("read", "unread", "newer", "newest")
    )
    with PreviewCache(tmp_path / "previews", limit_bytes=10_000, clock=clock) as cache:
        for key in (read, unread, newer):
            cache.put(key, INFO_NAME, _blob(3_000, key.content_key))
            clock.advance(TOUCH_INTERVAL_S + 1)
        hit = cache.get(read, INFO_NAME)
        clock.advance(TOUCH_INTERVAL_S + 1)

        # Act
        cache.put(newest, INFO_NAME, _blob(3_000, "newest"))
        kept = {key: cache.has(key, INFO_NAME) for key in (read, unread, newer, newest)}
        usage = cache.usage()

    # Assert
    assert hit == _blob(3_000, read.content_key)
    assert kept == {read: True, unread: False, newer: True, newest: True}
    assert usage == CacheUsage(used_bytes=9_000, limit_bytes=10_000, objects=3)
    assert usage.used_bytes <= EVICT_TO * usage.limit_bytes


def test_cache_limit_holds_with_builds(tmp_path: Path) -> None:
    """The limit (1 MB, 1 000 000 bytes) holds after every put; a build stays.

    An object pinned before its first file (being built) is never evicted,
    though the least recently used and later 302 kB with its COG; a put
    larger than the limit evicts everything else and itself. Unpinned, the
    object goes like any other.
    """
    # Arrange
    clock = Clock()
    rng = random.Random(7)
    built = _key("built")
    others = [_key(f"other-{number}") for number in range(12)]
    used: list[int] = []
    building: list[bool] = []
    with PreviewCache(tmp_path / "previews", limit_bytes=MB, clock=clock) as cache:
        cache.pin(built)
        cache.put(built, INFO_NAME, _blob(2_000, "built"))

        # Act
        for step in range(90):
            clock.advance(1)
            if step == 30:
                staged = cache.incoming_dir() / "cog.part"
                staged.write_bytes(_blob(300_000, "cog"))
                cache.put(built, COG_NAME, staged)
            if step == 70:
                cache.unpin(built)
            size = MB + 200_000 if step == 50 else rng.randrange(1_000, 250_000)
            name = tile_name("gray", 12, step, 0)
            cache.put(rng.choice(others), name, _blob(size, str(step)))
            used.append(cache.usage().used_bytes)
            if step < 70:
                building.append(
                    cache.has(built, INFO_NAME)
                    and (step < 30 or cache.has(built, COG_NAME))
                )
        released = not cache.has(built, INFO_NAME)

    # Assert
    assert max(used) <= MB
    assert building == [True] * 70
    assert released


def test_cache_survives_restart(tmp_path: Path) -> None:
    """Closed and opened again, the cache has the same objects and usage.

    A finished file is put by its path: it moves into the cache.
    """
    # Arrange
    root = tmp_path / "previews"
    raster, vector = _key("raster"), _key("vector", "vector")
    probe, cog, tile = b'{"kind": "raster"}', _blob(50_000, "cog"), _blob(700, "tile")
    with PreviewCache(root, limit_bytes=MB) as cache:
        cache.put(raster, INFO_NAME, probe)
        staged = cache.incoming_dir() / "cog.part"
        staged.write_bytes(cog)
        cache.put(raster, COG_NAME, staged)
        cache.put(vector, TILE, tile)
        before = cache.usage()

    # Act
    with PreviewCache(root, limit_bytes=MB) as reopened:
        usage = reopened.usage()
        probe_hit = reopened.get(raster, INFO_NAME)
        tile_hit = reopened.get(vector, TILE)
        handle = reopened.open(raster, COG_NAME)
        assert handle is not None
        with handle:
            cog_hit = handle.read()

    # Assert
    assert usage == before == CacheUsage(50_000 + len(probe) + 700, MB, 2)
    assert (probe_hit, tile_hit, cog_hit) == (probe, tile, cog)
    assert not staged.exists()


def test_cache_without_database_adopts_objects(tmp_path: Path) -> None:
    """Opened without ``cache.sqlite``, the cache accounts for its objects again."""
    # Arrange
    root = tmp_path / "previews"
    key = _key("adopted")
    with PreviewCache(root, limit_bytes=MB) as cache:
        cache.put(key, INFO_NAME, b'{"kind": "raster"}')
        cache.put(key, TILE, _blob(700, "tile"))
        before = cache.usage()
    (root / CACHE_FILE).unlink()

    # Act
    with PreviewCache(root, limit_bytes=MB) as reopened:
        usage = reopened.usage()
        hit = reopened.get(key, TILE)

    # Assert
    assert usage == before
    assert hit == _blob(700, "tile")


def test_cache_safe_across_processes(tmp_path: Path) -> None:
    """Four processes putting and reading at once keep the cache consistent.

    No process fails, reads a partial file or sees the usage over the
    limit; afterwards the rows agree with the files: the usage is what lies
    on the disk, and ``reconcile`` has nothing to change.
    """
    # Arrange
    root = tmp_path / "previews"
    limit = 200_000

    # Act
    with ExitStack() as stack:
        children = [_spawn(stack, SHARING, root, limit, seed) for seed in range(4)]
        _start_together(children)  # a child that ended fails at its return code
        finished = [child.communicate(timeout=CHILD_TIMEOUT_S) for child in children]
    with PreviewCache(root, limit_bytes=limit) as cache:
        before = cache.usage()
        on_disk = _on_disk(root)
        cache.reconcile()
        after = cache.usage()

    # Assert
    assert [child.returncode for child in children] == [0] * 4, finished
    counts = [json.loads(out) for out, _ in finished]
    assert [(count["damaged"], count["over_limit"]) for count in counts] == [(0, 0)] * 4
    assert sum(count["hits"] for count in counts) > 0
    assert before.used_bytes <= limit
    assert (before.used_bytes, before.objects) == on_disk
    assert after == before


def test_cache_opened_by_processes_at_once(tmp_path: Path) -> None:
    """Processes that open a new cache at the same moment all open it.

    The first open switches ``cache.sqlite`` to WAL, writing its header;
    SQLite refuses a process that read the header meanwhile at once, without
    the busy timeout ("database is locked"). Eight processes open each of five
    new caches together.
    """
    # Arrange
    roots = [tmp_path / f"previews-{round_}" for round_ in range(5)]

    # Act
    with ExitStack() as stack:
        children = [_spawn(stack, OPENING, *roots) for _ in range(8)]
        for _ in roots:
            if not _start_together(children):
                break
        finished = [child.communicate(timeout=CHILD_TIMEOUT_S) for child in children]

    # Assert
    assert [child.returncode for child in children] == [0] * 8, finished


def test_hit_survives_eviction_by_other_process(tmp_path: Path) -> None:
    """Bytes of a hit stay whole when another process evicts the object.

    ``get`` has read the tile already; the COG opened with ``open`` reads
    on to its end after its file is gone. The next read is a miss.
    """
    # Arrange
    root = tmp_path / "previews"
    key = _key("evicted")
    tile, cog = _blob(200_000, "tile"), _blob(3_000_000, "cog")
    with PreviewCache(root, limit_bytes=10 * MB) as cache:
        cache.put(key, TILE, tile)
        cache.put(key, COG_NAME, cog)
        hit = cache.get(key, TILE)
        handle = cache.open(key, COG_NAME)
        assert handle is not None
        with handle:
            head = handle.read(1_000)

            # Act
            evicted = _python(EVICTING, root)
            rest = handle.read()
        missed = cache.get(key, TILE)
        reopened = cache.open(key, COG_NAME)

    # Assert
    assert evicted.returncode == 0, evicted.stderr
    assert int(evicted.stdout) == len(tile) + len(cog)
    assert not (root / key.directory).exists()
    assert hit == tile
    assert head + rest == cog
    assert (missed, reopened) == (None, None)


def test_reconcile_after_crash(tmp_path: Path) -> None:
    """Reconciling settles what killed processes left behind.

    Files without rows are adopted with their size, their modification
    time as the use; rows without files dropped; ``.incoming`` of a dead
    process removed, of a live one (this) and of another host kept; the
    pin of a dead build no longer keeps its object.
    """
    # Arrange
    root = tmp_path / "previews"
    clock = Clock(1_000_000.0)
    kept, dropped, old, new = (_key(seed) for seed in ("kept", "dropped", "old", "new"))
    with PreviewCache(root, limit_bytes=MB, clock=clock) as cache:
        cache.put(kept, INFO_NAME, _blob(1_000, "kept"))
        clock.advance(10)
        cache.put(dropped, INFO_NAME, _blob(1_000, "dropped"))
        cache.put(dropped, TILE, _blob(500, "tile"))
    with subprocess.Popen(
        [sys.executable, "-c", CRASHING, str(root), str(MB), old.content_key],
        env=_child_env(),
    ) as build:
        assert build.wait(timeout=CHILD_TIMEOUT_S) == 0
    # Renamed in, never committed: files without rows (mtime as the use).
    leftovers = (
        (old, INFO_NAME, 2_000, 900_000.0),
        (new, INFO_NAME, 2_000, 1_100_000.0),
        (kept, "thumb-gray-256.png", 300, 950_000.0),
    )
    for key, name, size, modified in leftovers:
        path = root / key.directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_blob(size, name))
        os.utime(path, (modified, modified))
    # Removed, never committed: a row without its file.
    (root / dropped.directory / TILE).unlink()
    host = process_owner().rsplit("_", 1)[0]
    incoming = {
        "dead": f"{host}_{build.pid}_0a1b",
        "live": f"{process_owner()}_2c3d",
        "foreign": f"other-host_{build.pid}_4e5f",
    }
    for name in incoming.values():
        (root / INCOMING_DIR / name).mkdir()
        (root / INCOMING_DIR / name / "tile.part").write_bytes(b"x")

    # Act
    with PreviewCache(root, limit_bytes=MB, clock=clock) as cache:
        cache.reconcile()
        reconciled = cache.usage()
        cache.set_limit(reconciled.used_bytes - 1)
        evicted = cache.usage()
        named = {"kept": kept, "dropped": dropped, "old": old, "new": new}
        objects = {seed: cache.has(key, INFO_NAME) for seed, key in named.items()}
        adopted = cache.get(kept, "thumb-gray-256.png")
        lost = cache.get(dropped, TILE)

    # Assert
    assert reconciled == CacheUsage(1_300 + 1_000 + 2_000 + 2_000, MB, 4)
    assert objects == {"kept": True, "dropped": True, "old": False, "new": True}
    assert evicted == CacheUsage(4_300, 6_299, 3)
    assert adopted == _blob(300, "thumb-gray-256.png")
    assert lost is None
    left = {path.name for path in (root / INCOMING_DIR).iterdir()}
    assert incoming["dead"] not in left
    assert {incoming["live"], incoming["foreign"]} <= left


def test_renderer_version_bump_keeps_other_kinds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A new raster renderer version misses old raster objects, keeps vectors.

    ``reconcile`` removes the objects of the old version; the vector ones
    stay hits.
    """
    # Arrange
    root = tmp_path / "previews"
    raster = _source(tmp_path, "arkusz.tif", "raster bytes")
    vector = _source(tmp_path, "dzialki.gpkg", "vector bytes")
    vector_probe = b'{"kind": "vector"}'
    old_raster = cache_key(raster)
    with PreviewCache(root, limit_bytes=MB) as cache:
        cache.put(old_raster, INFO_NAME, b'{"kind": "raster"}')
        cache.put(cache_key(vector), INFO_NAME, vector_probe)
    monkeypatch.setattr(
        preview_cache,
        "RENDERER_VERSIONS",
        {**RENDERER_VERSIONS, "raster": old_raster.renderer_version + 1},
    )

    # Act
    with PreviewCache(root, limit_bytes=MB) as cache:
        raster_hit = cache.get(cache_key(raster), INFO_NAME)
        vector_hit = cache.get(cache_key(vector), INFO_NAME)
        cache.reconcile()
        usage = cache.usage()
        vector_after = cache.get(cache_key(vector), INFO_NAME)

    # Assert
    assert raster_hit is None
    assert vector_hit == vector_after == vector_probe
    assert not (root / old_raster.directory).exists()
    assert usage == CacheUsage(len(vector_probe), MB, 1)


@pytest.mark.parametrize(
    "name",
    [
        "",
        "/info.json",
        "../info.json",
        "tiles/../../../../../../x.png",
        "tiles//1.png",
        "tiles/./1.png",
        "thumb gray.png",
    ],
)
def test_cache_put_name_outside_object_refused(tmp_path: Path, name: str) -> None:
    """A file name is a relative path inside its object; another is refused."""
    # Arrange
    with PreviewCache(tmp_path / "previews", limit_bytes=MB) as cache:
        # Act
        with pytest.raises(ValueError):
            cache.put(_key("named"), name, b"x")
        usage = cache.usage()

    # Assert
    assert usage.used_bytes == 0
    assert list(tmp_path.rglob("*.png")) == []


def test_cache_composite_key_ignores_order_keeps_fields_apart() -> None:
    """A layer's key ignores the order of its contents, not where a field ends."""
    # Arrange
    first, second = (hashlib.sha256(seed).hexdigest() for seed in (b"1", b"2"))
    tile = "12/2275/1388"

    # Act
    key = composite_key("layer_tile", [first, second], tile, "gray", None)
    reordered = composite_key("layer_tile", [second, first], tile, "gray", None)
    others = {
        composite_key("layer_tile", [first, second], f"{tile}g", "ray", None),
        composite_key("layer_tile", [first], tile, "gray", None),
        composite_key("layer_tile", [first, second], tile, "gray", 0),
        composite_key("layer_thumbnail", [first, second], tile, "gray", None),
    }

    # Assert
    assert reordered == key
    assert key not in others
    assert len(others) == 4
    with pytest.raises(ValueError):
        composite_key("layer_tile", [first], f"{tile}\ngray", "", None)


@pytest.mark.filterwarnings("ignore:Dataset has no geotransform")
def test_same_raster_bytes_with_different_metadata_have_independent_previews(
    tmp_path: Path,
) -> None:
    """Indexed placement, style and hints partition all artifacts of shared bytes."""
    grid = tmp_path / "height.asc"
    data = store_files.asc_grid((19.0, 50.0, 20.0, 51.0), 31)
    grid.write_bytes(data)
    source = PreviewSource(
        ref="version:zespol:height.asc",
        content_key=hashlib.sha256(data).hexdigest(),
        paths=(grid,),
        crs="EPSG:4326",
        product="nmt",
    )
    other = replace(source, crs="EPSG:3857", product="orto")
    first_probe, second_probe = probe_raster(source), probe_raster(other)
    assert first_probe.bbox_wgs84 != second_probe.bbox_wgs84
    assert first_probe.default_style != second_probe.default_style

    with PreviewCache(tmp_path / "previews", limit_bytes=MB) as cache:
        cache.put(cache_key(source), INFO_NAME, first_probe.to_bytes())
        second_hit = cache.get(cache_key(other), INFO_NAME)
    assert second_hit is None

    # A change in any indexed rendering input must miss the same cache object.
    variants = (
        replace(source, crs="EPSG:3857"),
        replace(source, product="orto"),
        replace(source, nodata=0.0),
        replace(source, dataset_key="another_dataset"),
        replace(source, format_hint="JPEG"),
    )
    assert all(cache_key(item) != cache_key(source) for item in variants)

    # A layer must not reuse a composite drawn from the other placement/style.
    frame = {"bbox": [19.0, 50.0, 20.0, 51.0], "crs": "EPSG:4326"}
    layer_params = {
        "frame": frame,
        "style": "gray",
        "size": 256,
    }
    first_layer = layer_thumbnail_target(
        None, {**layer_params, "versions": [{"source": source.to_json()}]}
    )
    second_layer = layer_thumbnail_target(
        None, {**layer_params, "versions": [{"source": other.to_json()}]}
    )
    assert first_layer[0] != second_layer[0]

    image = tmp_path / "sheet.jpg"
    image_data = store_files.jpeg(31)
    image.write_bytes(image_data)
    first = PreviewSource(
        ref="version:zespol:sheet.jpg",
        content_key=hashlib.sha256(image_data).hexdigest(),
        paths=(image,),
        georeference=Extent((19.0, 50.0, 20.0, 51.0), "EPSG:4326"),
    )
    moved = replace(first, georeference=Extent((21.0, 51.0, 22.0, 52.0), "EPSG:4326"))
    assert probe_raster(first).bbox_wgs84 != probe_raster(moved).bbox_wgs84
    with PreviewCache(tmp_path / "images", limit_bytes=MB) as cache:
        cache.put(cache_key(first), INFO_NAME, probe_raster(first).to_bytes())
        assert cache.get(cache_key(moved), INFO_NAME) is None


def _twin(root: Path, version: str, label: str) -> str:
    """Write the same bytes as another version of the slot, labelled ``label``.

    A second download of unchanged data: its own ``<label>_<sha8>`` directory
    with the file and a sidecar of the same ``sha256``.
    """
    source = root / version
    sha8 = source.parent.name.rpartition("_")[2]
    directory = source.parent.parent / f"{label}_{sha8}"
    directory.mkdir()
    target = directory / source.name
    target.write_bytes(source.read_bytes())
    sidecar = source.with_name(source.name + ".meta.json")
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    meta["extra"]["version"]["label"] = label
    target.with_name(target.name + ".meta.json").write_text(
        json.dumps(meta), encoding="utf-8"
    )
    return target.relative_to(root).as_posix()


def _views(served: PreviewApi, path: str) -> tuple[bytes, bytes]:
    """Return the thumbnail and the central tile of a version, as the map asks."""
    info = served.get(version_url(path)).json()
    thumbnail = served.get(info["thumbnail_url"])
    tile = served.get(center_tile_url(info))
    assert (thumbnail.status_code, tile.status_code) == (200, 200)
    return thumbnail.content, tile.content


@pytest.mark.filterwarnings("ignore:Dataset has no geotransform")
def test_same_content_rendered_once(tmp_path: Path) -> None:
    """Two versions of one ``sha256`` render once; repeats and a restart do not.

    SPEC 13 v0.2, criterion 3: the first version's probe, thumbnail and tile
    are rendered; the second version of the same bytes (another label of
    the slot), repeated requests and a server started again over the same
    cache answer from it, so the render processes get no more requests.
    """
    # Arrange
    twins: list[str] = []

    def download_again(store: StoreManifest) -> None:
        version = entry_of(store, "tif_sheet", "regular").path
        twins.append(_twin(store.root, version, "2026-10-18_49291"))

    store, paths = scanned_store(tmp_path, before_scan=download_again)
    original, twin = entry_of(store, "tif_sheet", "regular").path, twins[0]

    # Act
    with serve_previews(store, paths) as served:
        first = _views(served, original)
        rendered = served.pool.stats().rendered
        second = _views(served, twin)
        repeated = [_views(served, path) for path in (original, twin, original)]
        before_restart = served.pool.stats().rendered
        refs = {
            served.get(version_url(path)).json()["ref"] for path in (original, twin)
        }
    with serve_previews(store, paths) as restarted:
        after = [_views(restarted, path) for path in (original, twin)]
        after_restart = restarted.pool.stats().rendered

    # Assert
    assert len(refs) == 2
    assert rendered == 3  # the probe, the thumbnail and the tile
    assert second == first and repeated == [first] * 3 and after == [first] * 2
    assert before_restart == rendered
    assert after_restart == 0
