"""A process supervising one scan, for the tests of a server that dies.

``python -m tests.fixtures.job_owner CONFIG DATA STORE`` starts a
``JobSupervisor`` with the test workers, submits a full scan of the store,
prints the job id and waits until killed or its standard input ends.
"""

import sys
from pathlib import Path

from archiwista.config import AppPaths, ConfigStore, SettingsService
from archiwista.jobs import JobSupervisor
from tests.fixtures.jobs import TEST_WORKER
from tests.fixtures.local_server import NoSources


def main(argv: list[str]) -> int:
    """Supervise a full scan of ``argv[2]`` until stopped."""
    config, data, store = argv
    paths = AppPaths(config_file=Path(config), data_dir=Path(data))
    settings = SettingsService(ConfigStore(paths.config_file), NoSources())
    with JobSupervisor(paths, settings, worker_command=TEST_WORKER) as jobs:
        job = jobs.submit("scan", store=store, params={"mode": "full"}, actor="local")
        print(job.id, flush=True)
        sys.stdin.read()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
