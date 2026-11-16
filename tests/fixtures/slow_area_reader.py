"""A stand-in area reader that never answers: it records its pid and sleeps.

``AreaFiles.command`` set to this script shows that the server kills a reader
at its time limit; ``PID_FILE_ENV`` names the file receiving the pid.
"""

import os
import sys
import time
from pathlib import Path

PID_FILE_ENV = "ARCHIWISTA_SLOW_READER_PID"


def main() -> int:
    """Record the process id, then sleep far past any limit of a test."""
    Path(os.environ[PID_FILE_ENV]).write_text(str(os.getpid()), encoding="utf-8")
    time.sleep(120)
    return 0


if __name__ == "__main__":
    sys.exit(main())
