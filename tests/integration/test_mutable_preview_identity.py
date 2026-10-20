"""Mutable own-data identities must not publish results under stale cache keys."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from archiwista.errors import PreviewUnavailableError
from archiwista.owndata.scan import snapshot_stamp, stamp_holds
from archiwista.previews.cache import INFO_NAME, PreviewCache, cache_key
from archiwista.previews.pool import RenderPool
from archiwista.previews.types import FileStat, PreviewSource, SourceStat
from tests.fixtures.render_worker import TEST_RENDER_WORKER


def _replace_preserving_size_and_mtime(path: Path, content: bytes) -> None:
    """Replace the inode with different, same-length bytes and the old mtime."""
    old = path.stat()
    assert len(content) == old.st_size
    replacement = path.with_name(f"{path.name}.new")
    replacement.write_bytes(content)
    os.utime(replacement, ns=(old.st_atime_ns, old.st_mtime_ns))
    os.replace(replacement, path)


def test_working_stamp_rejects_replaced_inode_with_restored_mtime(
    tmp_path: Path,
) -> None:
    """A same-size replacement does not reuse a working file's scan stamp."""
    source = tmp_path / "working.geojson"
    source.write_bytes(b"first file")
    found = source.stat()
    stamp = json.dumps([[source.name, found.st_size, found.st_mtime_ns]])

    _replace_preserving_size_and_mtime(source, b"other file")

    assert not stamp_holds(source, stamp)


def test_snapshot_stamp_changes_when_copy_replaced_without_mtime_change(
    tmp_path: Path,
) -> None:
    """A changed snapshot copy forces the next scan to validate its digest."""
    copy = tmp_path / "copy.geojson"
    copy.write_bytes(b"first file")
    before, size = snapshot_stamp(tmp_path)

    _replace_preserving_size_and_mtime(copy, b"other file")

    after, new_size = snapshot_stamp(tmp_path)
    assert size == new_size
    assert before != after


def test_worker_refuses_stale_content_before_publishing_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even a fresh stat cannot authorize bytes under an old indexed digest."""
    old = b'{"name":"a","needs_cog":false}'
    new = b'{"name":"b","needs_cog":false}'
    path = tmp_path / "own.json"
    path.write_bytes(old)
    indexed_digest = hashlib.sha256(old).hexdigest()
    _replace_preserving_size_and_mtime(path, new)
    found = path.stat()
    # The worker must compare actual content, not merely trust the current
    # stat passed from the resolver (a race, or an older index with weak stamps).
    source = PreviewSource(
        f"file:project:{path.name}",
        indexed_digest,
        (path,),
        mutable=True,
        stat=SourceStat(FileStat.of(found)),
    )
    monkeypatch.setattr(
        "archiwista.previews.pool.RENDER_WORKER_COMMAND", TEST_RENDER_WORKER
    )
    with (
        PreviewCache(tmp_path / "cache", limit_bytes=10 * 1024**2) as cache,
        RenderPool(cache=cache, workers=1, work_dir=tmp_path / "work") as pool,
        pytest.raises(PreviewUnavailableError) as failure,
    ):
        pool.request("probe", source)
    assert failure.value.reason == "changed_since_scan"
    with PreviewCache(tmp_path / "cache", limit_bytes=10 * 1024**2) as cache:
        assert not cache.has(cache_key(source), INFO_NAME)
