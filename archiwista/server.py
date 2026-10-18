"""``archiwista serve`` and ``archiwista token``: the local server and its tokens.

``serve`` refuses any listening address but ``127.0.0.1`` before doing
anything else (team mode with login comes in v0.4), binds the port, issues
the one-time startup token, prints ``http://127.0.0.1:<port>/#token=…``,
optionally opens it in the browser and serves until Ctrl+C. The browser gets
the address through a private file (``LaunchFile``), never on its command
line, which other accounts of the computer can read. Uvicorn's access log is
off unless asked for; when on, ``token=`` values are redacted; it serves at
most ``LIMIT_CONCURRENCY`` connections at once. While it serves, background
jobs run under its ``JobSupervisor`` and the ``ScanScheduler`` scans the
stores; stopping ends the open job event streams first (they would hold it
until their jobs end), then interrupts running jobs. ``token`` prints the
one-time address of an agent's session, or ends every agent session
(``--revoke-all``).
"""

import contextlib
import copy
import html
import os
import secrets
import socket
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path
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
)
from archiwista.errors import StateError
from archiwista.index.schema import IndexUnsupportedError, initialize
from archiwista.jobs import JobSupervisor, ScanScheduler
from archiwista.messages import MESSAGES, with_detail
from archiwista.paths import private_directory
from archiwista.security import (
    AGENT_SESSION_MAX_AGE,
    LOOPBACK_HOST,
    TOKEN_TTL,
    SessionStore,
    TokenKind,
    TokenRedactionFilter,
    fragment_url,
    issue_one_time_token,
    revoke_agent_sessions,
)
from archiwista.sources.registry import PluginRegistry
from archiwista.state import StateStore

# Connections and tasks served at once; more are answered ``503``.
LIMIT_CONCURRENCY = 100

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
    # asyncio disables Nagle's algorithm only on connections accepted by an
    # IPPROTO_TCP socket; with it on, a response written in parts waits for
    # the client's delayed acknowledgement (about 40 ms per kept-alive request).
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
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


class _Uvicorn(uvicorn.Server):
    """Uvicorn calling ``on_stop`` before it waits for open connections."""

    def __init__(self, config: uvicorn.Config, on_stop: Callable[[], None]) -> None:
        super().__init__(config)
        self._on_stop = on_stop

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        """Call ``on_stop``, then shut down as Uvicorn does."""
        self._on_stop()
        await super().shutdown(sockets=sockets)


class LaunchFile:
    """The startup address in a private file that the browser opens.

    A browser started with the address keeps it on its command line, which
    other accounts of the computer can read (``/proc/<pid>/cmdline``), and
    whoever uses the one-time token first gets the owner's session. The
    browser therefore opens ``<directory>/open-<random>.html`` instead,
    readable by the owner only, which redirects to the address (as Jupyter
    does). Thread-safe.

    Parameters
    ----------
    directory : Path
        The private data directory (``AppPaths.data_dir``).
    """

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._path: Path | None = None
        self._lock = threading.Lock()

    @property
    def path(self) -> Path | None:
        """The file while it exists."""
        return self._path

    def write(self, url: str) -> Path:
        """Write the file redirecting to ``url`` (mode ``0600``) and return it."""
        address = html.escape(url, quote=True)
        page = (
            '<!doctype html>\n<html lang="pl">\n<head>\n<meta charset="utf-8">\n'
            f'<meta http-equiv="refresh" content="0;url={address}">\n'
            "<title>Archiwista</title>\n</head>\n"
            f'<body><p><a href="{address}">{MESSAGES["serve_launch_link"]}</a></p>'
            "</body>\n</html>\n"
        )
        with self._lock:
            self._remove()
            private_directory(self._directory)
            path = self._directory / f"open-{secrets.token_hex(8)}.html"
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                file.write(page)
            self._path = path
        return path

    def remove(self) -> None:
        """Delete the file (its token is used or expired, or the server stops)."""
        with self._lock:
            self._remove()

    def _remove(self) -> None:
        if self._path is not None:
            self._path.unlink(missing_ok=True)
            self._path = None


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
    launch : LaunchFile
        Where ``open_in_browser`` puts the address for the browser.
    access_log : bool
        Write Uvicorn's access log, with ``token=`` values redacted.
    on_stop : Callable[[], None]
        Called as the server starts to stop, before it waits for open
        connections; ends the application's long-lived responses (event
        streams).
    """

    def __init__(
        self,
        sock: socket.socket,
        app: ASGIApp,
        *,
        url: str,
        launch: LaunchFile,
        access_log: bool,
        on_stop: Callable[[], None],
    ) -> None:
        self.url = url
        self.launch = launch
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
            limit_concurrency=LIMIT_CONCURRENCY,
        )
        self._server = _Uvicorn(config, on_stop)

    def run(self) -> None:
        """Serve until ``stop`` or, in the main thread, Ctrl+C."""
        # On Ctrl+C Uvicorn shuts down gracefully, then re-raises the signal.
        with contextlib.suppress(KeyboardInterrupt):
            self._server.run(sockets=[self._socket])

    def stop(self) -> None:
        """Ask the server to finish; ``run`` returns shortly. Thread-safe."""
        self._server.should_exit = True


def open_in_browser(server: LocalServer) -> None:
    """Open the server's one-time address in the default browser, not waiting.

    The browser gets the ``file:`` address of ``server.launch``, never the
    token itself.
    """
    uri = server.launch.write(server.url).as_uri()
    threading.Thread(target=webbrowser.open, args=(uri,), daemon=True).start()


def serve_main(
    paths: AppPaths,
    registry: PluginRegistry,
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
    registry : PluginRegistry
        Producer plugins: settings validation, the scan scheduler and the
        API's requests needing a producer.
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
        serves, e.g. ``open_in_browser``. The launch file goes once the
        startup token is used, when it expires, and when the server stops.

    Returns
    -------
    int
        ``0`` after a normal stop, ``2`` for a refused address, ``1`` when
        the settings, the index, the state database, the jobs directory or
        the port cannot be used.
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
        state = StateStore(paths.state_file)
    except (SettingsValidationError, IndexUnsupportedError, StateError) as error:
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
        jobs = JobSupervisor(paths, settings)
        try:
            jobs.start()
        except OSError as error:
            err.write(with_detail(MESSAGES["serve_failed"], str(error)) + "\n")
            return 1
        scheduler = ScanScheduler(jobs, settings, registry, index_path=paths.index_file)
        launch = LaunchFile(paths.data_dir)
        expiry = threading.Timer(TOKEN_TTL["startup"].total_seconds(), launch.remove)
        expiry.daemon = True

        def redeemed(kind: TokenKind) -> None:
            if kind == "startup":
                launch.remove()

        try:
            app = create_app(
                port=bound_port,
                settings=settings,
                index_path=paths.index_file,
                state=state,
                registry=registry,
                areas_dir=paths.areas_dir,
                sessions=SessionStore(),
                jobs=jobs,
                on_redeem=redeemed,
            )
            issued = issue_one_time_token(
                paths.index_file, "startup", minted_by=LOCAL_OWNER
            )
            server = LocalServer(
                sock,
                app,
                url=fragment_url(bound_port, issued.token),
                launch=launch,
                access_log=access_log,
                on_stop=app.state.job_streams.close,
            )
            out.write(
                MESSAGES["serve_started"].format(
                    url=server.url, minutes=_minutes("startup")
                )
                + "\n"
            )
            out.flush()
            expiry.start()
            if on_ready is not None:
                on_ready(server)
            scheduler.start()
            server.run()
        finally:
            expiry.cancel()
            launch.remove()
            scheduler.stop()
            jobs.close()
    return 0


def token_main(
    paths: AppPaths,
    out: TextIO,
    err: TextIO,
    *,
    port: int | None = None,
    as_json: bool = False,
    revoke_all: bool = False,
) -> int:
    """Run ``archiwista token``: a one-time address of an agent's session.

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
    revoke_all : bool, optional
        Issue nothing: end every agent session, also of a running server,
        and refuse the agent tokens not used yet.

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
    if revoke_all:
        refused = revoke_agent_sessions(paths.index_file)
        out.write(MESSAGES["token_revoked"].format(count=refused) + "\n")
        return 0
    # The owner at the terminal mints a token for an agent acting for them.
    issued = issue_one_time_token(paths.index_file, "agent", minted_by=LOCAL_OWNER)
    token = OneTimeToken(
        token=issued.token,
        url=fragment_url(settings.port if port is None else port, issued.token),
        label=issued.label,
        expires_at=issued.expires_at,
    )
    if as_json:
        out.write(token.model_dump_json() + "\n")
        return 0
    out.write(token.url + "\n")
    expires = issued.expires_at.astimezone().strftime("%H:%M")
    message = MESSAGES["token_issued"].format(
        label=issued.label,
        minutes=_minutes("agent"),
        time=expires,
        hours=int(AGENT_SESSION_MAX_AGE.total_seconds()) // 3600,
    )
    err.write(message + "\n")
    return 0


def _minutes(kind: TokenKind) -> int:
    return int(TOKEN_TTL[kind].total_seconds()) // 60
