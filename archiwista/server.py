"""``archiwista serve`` and ``archiwista token``: the local server and its tokens.

``serve`` refuses any listening address but ``127.0.0.1`` before doing
anything else (team mode with login comes in v0.4), binds the port, issues
the one-time startup token, prints ``http://127.0.0.1:<port>/#token=…``,
optionally opens it in the browser and serves until Ctrl+C. Uvicorn's access
log is off unless asked for; when on, ``token=`` values are redacted.
``token`` prints the one-time address of a next session, e.g. for an agent.
"""

import contextlib
import copy
import os
import socket
import threading
import webbrowser
from collections.abc import Callable
from typing import Any, TextIO

import uvicorn
from starlette.types import ASGIApp
from uvicorn.config import LOGGING_CONFIG

from archiwista.api.session import OneTimeToken
from archiwista.app import create_app
from archiwista.auth import LOCAL_OWNER
from archiwista.config import (
    AppPaths,
    ConfigStore,
    SettingsService,
    SettingsValidationError,
    SourceRegistryView,
)
from archiwista.index.schema import IndexUnsupportedError, initialize
from archiwista.messages import MESSAGES, with_detail
from archiwista.security import (
    LOOPBACK_HOST,
    TOKEN_TTL,
    SessionStore,
    TokenKind,
    TokenRedactionFilter,
    fragment_url,
    issue_one_time_token,
)

_REDACT_FILTER = "archiwista_redact_tokens"


def uvicorn_log_config() -> dict[str, Any]:
    """Return Uvicorn's logging setup with ``token=`` values hidden.

    The filter sits on the ``uvicorn.access`` logger, so the request line is
    redacted before any handler sees it.
    """
    config = copy.deepcopy(LOGGING_CONFIG)
    config["filters"] = {_REDACT_FILTER: {"()": TokenRedactionFilter}}
    config["loggers"]["uvicorn.access"]["filters"] = [_REDACT_FILTER]
    return config


def bind_loopback(port: int) -> socket.socket:
    """Listen on ``127.0.0.1:<port>``; ``0`` picks a free port.

    Raises
    ------
    OSError
        If the port is taken or not allowed.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name == "posix":
            # Restart at once even with connections of a stopped server in
            # TIME_WAIT (on Windows this option would allow port sharing).
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((LOOPBACK_HOST, port))
        sock.listen()
    except BaseException:
        sock.close()
        raise
    return sock


class LocalServer:
    """The application on a listening loopback socket, ready to serve.

    Parameters
    ----------
    sock : socket.socket
        Socket from ``bind_loopback``; the server closes it when it stops.
    app : ASGIApp
        The application.
    url : str
        One-time address of the first session.
    access_log : bool
        Write Uvicorn's access log, with ``token=`` values redacted.
    """

    def __init__(
        self, sock: socket.socket, app: ASGIApp, *, url: str, access_log: bool
    ) -> None:
        self.url = url
        self.port: int = sock.getsockname()[1]
        self._socket = sock
        config = uvicorn.Config(
            app,
            host=LOOPBACK_HOST,
            port=self.port,
            log_config=uvicorn_log_config(),
            access_log=access_log,
            proxy_headers=False,
            server_header=False,
        )
        self._server = uvicorn.Server(config)

    def run(self) -> None:
        """Serve until ``stop`` or, in the main thread, Ctrl+C."""
        # On Ctrl+C Uvicorn shuts down gracefully, then re-raises the signal.
        with contextlib.suppress(KeyboardInterrupt):
            self._server.run(sockets=[self._socket])

    def stop(self) -> None:
        """Ask the server to finish; ``run`` returns shortly. Thread-safe."""
        self._server.should_exit = True


def open_in_browser(server: LocalServer) -> None:
    """Open the server's one-time address in the default browser, not waiting."""
    threading.Thread(target=webbrowser.open, args=(server.url,), daemon=True).start()


def serve_main(
    paths: AppPaths,
    registry: SourceRegistryView,
    out: TextIO,
    err: TextIO,
    *,
    host: str = LOOPBACK_HOST,
    port: int | None = None,
    access_log: bool = False,
    on_ready: Callable[[LocalServer], object] | None = None,
) -> int:
    """Run ``archiwista serve`` and return the process exit status.

    Parameters
    ----------
    paths : AppPaths
        Configuration file and local data.
    registry : SourceRegistryView
        Producer plugins, for validating settings changes.
    out, err : TextIO
        Streams for the address and for errors.
    host : str, optional
        Listening address; anything but ``127.0.0.1`` is refused before any
        other step.
    port : int or None, optional
        Port; the configured one when omitted, a free one for ``0``.
    access_log : bool, optional
        Write the access log (``token=`` values redacted); off by default.
    on_ready : Callable[[LocalServer], object] or None, optional
        Called with the server after the address is printed and before it
        serves, e.g. ``open_in_browser``.

    Returns
    -------
    int
        ``0`` after a normal stop, ``2`` for a refused address, ``1`` when
        the settings, the index or the port cannot be used.
    """
    if host != LOOPBACK_HOST:
        message = MESSAGES["serve_host_refused"].format(
            host=host, loopback=LOOPBACK_HOST
        )
        err.write(message + "\n")
        return 2
    try:
        settings = SettingsService(ConfigStore(paths.config_file), registry)
        initialize(paths.index_file)
    except (SettingsValidationError, IndexUnsupportedError) as error:
        err.write(with_detail(MESSAGES["serve_failed"], str(error)) + "\n")
        return 1
    if port is None:
        port = settings.get().port
    try:
        sock = bind_loopback(port)
    except OSError as error:
        message = MESSAGES["serve_port_unavailable"].format(
            host=LOOPBACK_HOST, port=port
        )
        err.write(with_detail(message, error.strerror or str(error)) + "\n")
        return 1
    with sock:
        bound_port: int = sock.getsockname()[1]
        app = create_app(
            port=bound_port,
            settings=settings,
            index_path=paths.index_file,
            sessions=SessionStore(),
        )
        issued = issue_one_time_token(
            paths.index_file, "startup", minted_by=LOCAL_OWNER
        )
        server = LocalServer(
            sock,
            app,
            url=fragment_url(bound_port, issued.token),
            access_log=access_log,
        )
        out.write(
            MESSAGES["serve_started"].format(
                url=server.url, minutes=_minutes("startup")
            )
            + "\n"
        )
        out.flush()
        if on_ready is not None:
            on_ready(server)
        server.run()
    return 0


def token_main(
    paths: AppPaths,
    out: TextIO,
    err: TextIO,
    *,
    port: int | None = None,
    as_json: bool = False,
) -> int:
    """Run ``archiwista token``: a one-time address of a next session.

    Parameters
    ----------
    paths : AppPaths
        Configuration file and local index.
    out, err : TextIO
        The address (or JSON) goes to ``out``, explanations to ``err``.
    port : int or None, optional
        Port in the address; the configured one when omitted.
    as_json : bool, optional
        Print the ``POST /api/v1/session/tokens`` response model instead.

    Returns
    -------
    int
        ``0``, or ``1`` when the settings or the index cannot be used.
    """
    try:
        settings = ConfigStore(paths.config_file).load()
        initialize(paths.index_file)
    except (SettingsValidationError, IndexUnsupportedError) as error:
        err.write(with_detail(MESSAGES["token_failed"], str(error)) + "\n")
        return 1
    # The owner at the terminal mints a token for an agent acting for them.
    issued = issue_one_time_token(paths.index_file, "agent", minted_by=LOCAL_OWNER)
    token = OneTimeToken(
        token=issued.token,
        url=fragment_url(settings.port if port is None else port, issued.token),
        expires_at=issued.expires_at,
    )
    if as_json:
        out.write(token.model_dump_json() + "\n")
        return 0
    out.write(token.url + "\n")
    expires = issued.expires_at.astimezone().strftime("%H:%M")
    message = MESSAGES["token_issued"].format(minutes=_minutes("agent"), time=expires)
    err.write(message + "\n")
    return 0


def _minutes(kind: TokenKind) -> int:
    return int(TOKEN_TTL[kind].total_seconds()) // 60
