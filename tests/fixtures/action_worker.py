"""Worker process of the action tests: the real worker, the stand-in in each store.

The settings reach a worker as JSON, so a store keeps only the directories of
the producers Archiwista configures. This worker gives each store's Kartograf
directory to the stand-in, as ``tests.fixtures.actions.StandinStore`` does in
the test's own process, and runs the real worker.
"""

import sys
from pathlib import Path

from archiwista.config import StoreConfig, StoreDirectory
from archiwista.jobs import worker
from tests.fixtures.actions import standin_directories, standin_roots


def main() -> int:
    """Give the stand-in its directory in every store and run the real worker."""
    roots, directories = StoreConfig.roots, StoreConfig.directories

    def standin(self: StoreConfig) -> dict[str, Path]:
        return standin_roots(roots(self))

    def standin_only(self: StoreConfig) -> tuple[StoreDirectory, ...]:
        return standin_directories(directories(self))

    StoreConfig.roots = standin  # type: ignore[method-assign]
    StoreConfig.directories = standin_only  # type: ignore[method-assign]
    return worker.main()


if __name__ == "__main__":
    sys.exit(main())
