"""Command-line entry point for Archiwista."""

import argparse

from archiwista.messages import MESSAGES


def main(argv: list[str] | None = None) -> int:
    """Parse the available command-line options.

    Parameters
    ----------
    argv : list[str] or None, optional
        Arguments to parse, or process arguments when omitted.

    Returns
    -------
    int
        Successful exit status.
    """
    parser = argparse.ArgumentParser(
        prog="archiwista", description=MESSAGES["cli_description"]
    )
    parser.parse_args(argv)
    return 0
