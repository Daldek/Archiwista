"""Worker process of the warm-up tests: the real worker, its renders slowed down.

A test's ``JobSupervisor`` starts ``python -m tests.fixtures.warm_worker``
(``WARM_WORKER``). With ``ARCHIWISTA_TEST_WARM_DELAY_S`` in the environment the
worker inherits, the ``preview_warm`` job waits that many seconds before it
renders each file, so a warm-up lasts long enough to be watched, overtaken
by a person's preview or cancelled. Everything else is the real worker.
"""

import os
import sys
import time
from typing import Any

from archiwista.jobs import worker
from archiwista.previews import warm

WARM_WORKER: tuple[str, ...] = (sys.executable, "-m", "tests.fixtures.warm_worker")
DELAY_ENV = "ARCHIWISTA_TEST_WARM_DELAY_S"


def main() -> int:
    """Slow down each file's render as the environment says; run the real worker."""
    delay = float(os.environ.get(DELAY_ENV, "0"))
    if delay:
        render = warm.Warmer._render

        def slowed(self: warm.Warmer, ref: str) -> Any:
            time.sleep(delay)
            return render(self, ref)

        warm.Warmer._render = slowed  # type: ignore[method-assign]
    return worker.main()


if __name__ == "__main__":
    sys.exit(main())
