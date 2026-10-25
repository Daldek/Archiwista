"""A socket guard: the test process may not reach the network in a block.

``no_network`` makes every connection and every name lookup of the test
process fail and records it, so a block that must work offline shows that it
tried nothing: a producer that caught the failure and went on would still
leave its attempt in the record. A test client of the application calls it
in the process, without a socket.
"""

import socket
from collections.abc import Iterator
from contextlib import contextmanager

import pytest


@contextmanager
def no_network() -> Iterator[list[str]]:
    """Refuse every connection and name lookup in the block.

    Yields
    ------
    list[str]
        What the block tried, one entry per attempt; empty when it tried
        nothing.
    """
    attempts: list[str] = []

    def refuse(*args: object, **kwargs: object) -> object:
        attempts.append(f"{args!r} {kwargs!r}")
        raise OSError("the test allows no network")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(socket.socket, "connect", refuse)
        patch.setattr(socket.socket, "connect_ex", refuse)
        patch.setattr(socket, "create_connection", refuse)
        patch.setattr(socket, "getaddrinfo", refuse)
        yield attempts
