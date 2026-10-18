"""Fixtures of the unit tests."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from archiwista.index import IndexQueries, IndexWriter
from tests.fixtures.index_data import ROOT, STORE


@pytest.fixture
def index(tmp_path: Path) -> Iterator[tuple[IndexWriter, IndexQueries]]:
    """Yield a writer and queries of an empty index with the store ``zespol``."""
    path = tmp_path / "index.sqlite"
    with IndexWriter(path) as writer, IndexQueries(path) as queries:
        writer.sync_stores({STORE: {"kartograf": ROOT}})
        yield writer, queries
