"""Worker process of Obserwator's job tests: the real worker, IMGW-PIB stood in for.

Obserwator's HTTP layer answers from its own fixtures
(``tests.fixtures.obserwator_http.standin_source``) for the whole job, so a
``check``, ``download`` or project job of Obserwator's commands runs in a real
worker process without the network. ``ETAGS_ENV`` names a JSON file of the
``ETag`` a test gives a server path (a newer version at the source); each job
starts its own process and reads it then.
"""

import json
import os
import sys
from pathlib import Path

from archiwista.jobs import worker
from tests.fixtures.obserwator_http import standin_source

ETAGS_ENV = "ARCHIWISTA_TEST_OBSERWATOR_ETAGS"
OBSERWATOR_WORKER: tuple[str, ...] = (
    sys.executable,
    "-m",
    "tests.fixtures.obserwator_worker",
)


def main() -> int:
    """Run the real worker with Obserwator's source stood in for."""
    named = os.environ.get(ETAGS_ENV)
    with standin_source() as source:
        if named and Path(named).is_file():
            source.etags.update(json.loads(Path(named).read_text(encoding="utf-8")))
        return worker.main()


if __name__ == "__main__":
    sys.exit(main())
