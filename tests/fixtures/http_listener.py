"""A listener on 127.0.0.1 noting every connection, to show nothing was fetched.

``listening()`` yields a ``Listener`` whose ``url`` an uploaded file can point
to; each connection is answered ``404`` and its first bytes are kept in
``received``. Leaving the block also takes the connections still waiting to
be accepted, so ``received`` is complete once the block is left.
"""

import contextlib
import socket
import threading
from collections.abc import Iterator

_ANSWER = b"HTTP/1.0 404 Not Found\r\nContent-Length: 0\r\n\r\n"
_POLL_S = 0.05


class Listener:
    """A TCP server on a free port of 127.0.0.1 keeping what it receives."""

    def __init__(self) -> None:
        self._socket = socket.create_server(("127.0.0.1", 0))
        self._socket.settimeout(_POLL_S)
        port = self._socket.getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"
        self.received: list[bytes] = []
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def close(self) -> None:
        """Stop serving, take the connections not yet accepted, close."""
        self._stopped.set()
        self._thread.join()
        self._socket.setblocking(False)
        with self._socket:
            while True:
                try:
                    connection, _ = self._socket.accept()
                except BlockingIOError:
                    return
                self._answer(connection)

    def _serve(self) -> None:
        while not self._stopped.is_set():
            try:
                connection, _ = self._socket.accept()
            except TimeoutError:
                continue
            self._answer(connection)

    def _answer(self, connection: socket.socket) -> None:
        with connection:
            connection.settimeout(1.0)
            try:
                self.received.append(connection.recv(1024))
            except OSError:
                self.received.append(b"")
            with contextlib.suppress(OSError):
                connection.sendall(_ANSWER)


@contextlib.contextmanager
def listening() -> Iterator[Listener]:
    """Yield a running listener; close it when the block is left."""
    listener = Listener()
    try:
        yield listener
    finally:
        listener.close()
