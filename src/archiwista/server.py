"""``archiwista serve`` and ``archiwista token``: the server and its tokens.

``serve`` first checks where it may listen (``team_refusal``): in local mode
only on ``127.0.0.1``; in team mode (the table ``[team]``, ADR-046) on an IP
address of this computer with TLS in the server, or behind trusted reverse
proxies on a specific address. Team mode also needs an administrator who can
sign in (``admin_refusal``). It then binds the port and, in local mode,
issues the one-time startup token, prints
``http://127.0.0.1:<port>/#token=…`` and optionally opens it in the browser;
in team mode it issues no token, opens no browser and prints the team's
``origin``. It serves until Ctrl+C. The browser gets the address through a
private file (``LaunchFile``), never on its command line, which other
accounts of the computer can read. Uvicorn's access log is off unless asked
for; when on, ``token=`` values are redacted; it serves at most
``LIMIT_CONCURRENCY`` connections at once. While it serves, background jobs
run under its ``JobSupervisor``, the ``ScanScheduler`` scans the stores and
the ``RenderPool`` renders previews into the preview cache (reconciled at the
start); stopping ends the open job event streams first (they would hold it
until their jobs end), then interrupts running jobs and ends the render
processes. ``token`` prints the one-time address of an agent's session, or
ends every agent session (``--revoke-all``).
"""

import contextlib
import copy
import html
import ipaddress
import os
import secrets
import socket
import sqlite3
import threading
import webbrowser
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

import uvicorn
from starlette.types import ASGIApp
from uvicorn.config import LOGGING_CONFIG

from archiwista.api.session import OneTimeToken
from archiwista.app import create_app
from archiwista.auth import LOCAL_OWNER
from archiwista.auth.passwords import sign_in_administrators
from archiwista.config import (
    AppPaths,
    AppSettings,
    ConfigStore,
    SettingsService,
    SettingsValidationError,
)
from archiwista.error_document import exception_problem, fail, refuse
from archiwista.errors import StateError
from archiwista.index.schema import IndexUnsupportedError, initialize
from archiwista.jobs import JobSupervisor, ScanScheduler
from archiwista.logs import DEFAULT_LOG_LEVEL
from archiwista.messages import message, with_detail
from archiwista.paths import private_directory
from archiwista.previews.cache import PreviewCache
from archiwista.previews.pool import RenderPool, default_render_workers
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
    tls_problem,
)
from archiwista.sources.registry import PluginRegistry
from archiwista.state import StateStore, UserRecord

# Connections and tasks served at once; more are answered ``503``.
LIMIT_CONCURRENCY = 100

_REDACT_FILTER = "archiwista_redact_tokens"


def uvicorn_log_config(level: str = DEFAULT_LOG_LEVEL) -> dict[str, Any]:
    """Return Uvicorn's logging setup at ``level`` with ``token=`` values hidden.

    The filter sits on the ``uvicorn.access`` logger, so the request line is
    redacted before any handler sees it. Only the server's own messages follow
    ``level``: the access log, when asked for, keeps writing every request.

    Parameters
    ----------
    level : str, optional
        A key of ``archiwista.logs.LOG_LEVELS``.
    """
    config = copy.deepcopy(LOGGING_CONFIG)
    config["filters"] = {_REDACT_FILTER: {"()": TokenRedactionFilter}}
    config["loggers"]["uvicorn.access"]["filters"] = [_REDACT_FILTER]
    for name in ("uvicorn", "uvicorn.error"):
        config["loggers"][name]["level"] = level.upper()
    return config


@dataclass(frozen=True, slots=True)
class Refusal:
    """Why ``archiwista serve`` does not start on an address (exit 2).

    Parameters
    ----------
    reason : str
        ``details.reason`` of the ``validation_error``.
    text : str
        What is wrong, a catalog message.
    hint : str
        How to fix it, a catalog message.
    """

    reason: str
    text: str
    hint: str


def team_refusal(settings: AppSettings, host: str) -> Refusal | None:
    """Return why the server may not listen on ``host``, or ``None`` (ADR-046).

    Local mode listens on ``127.0.0.1`` only (``host_refused``). Team mode
    listens on an IP address of this computer (``host_refused`` for a name),
    with TLS in the server, whose files must load as a pair
    (``tls_unusable``), or else behind trusted proxies (``tls_required``
    without them): then on a specific address (``proxy_bind_wildcard``),
    and on a loopback one when every trusted proxy is one
    (``proxy_bind_not_loopback``). Nothing is bound.

    Parameters
    ----------
    settings : AppSettings
        Settings with the table ``[team]``.
    host : str
        The address of ``--host``.
    """
    team = settings.team
    if not team.enabled:
        if host == LOOPBACK_HOST:
            return None
        text = message("serve.host_refused", host=host, loopback=LOOPBACK_HOST)
        return Refusal("host_refused", text, message("serve.hint_host_refused"))
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        text = message("serve.host_not_address", host=host)
        return Refusal("host_refused", text, message("serve.hint_host_address"))
    if team.tls_cert is not None and team.tls_key is not None:
        problem = tls_problem(team.tls_cert, team.tls_key)
        if problem is None:
            return None
        files = message("serve.tls_unusable", cert=team.tls_cert, key=team.tls_key)
        unusable = with_detail(files, problem)
        return Refusal("tls_unusable", unusable, message("serve.hint_tls_unusable"))
    networks = team.trusted_networks()
    if not networks:
        text = message("serve.tls_required")
        return Refusal("tls_required", text, message("serve.hint_tls_required"))
    if address.is_unspecified:
        text = message("serve.proxy_bind_wildcard", host=host)
        hint = message("serve.hint_proxy_bind_wildcard")
        return Refusal("proxy_bind_wildcard", text, hint)
    if all(network.is_loopback for network in networks) and not address.is_loopback:
        text = message("serve.proxy_bind_not_loopback", host=host)
        hint = message("serve.hint_proxy_bind_not_loopback")
        return Refusal("proxy_bind_not_loopback", text, hint)
    return None


def admin_refusal(settings: AppSettings, users: Iterable[UserRecord]) -> Refusal | None:
    """Return ``team_no_admin`` when team mode has no administrator to sign in.

    Team mode needs an enabled account with the role ``admin`` that can sign
    in: with a password that has not expired, or through the reverse proxy
    when ``proxy_user_header`` is set (``sign_in_administrators``). Otherwise
    nobody could manage the team, and nobody could create the first
    administrator from the network (ADR-046 decisions 2 and 4).

    Parameters
    ----------
    settings : AppSettings
        Settings with the table ``[team]``; local mode refuses nothing here.
    users : Iterable[UserRecord]
        Every account of the state database.
    """
    team = settings.team
    proxy = team.proxy_user_header is not None
    if not team.enabled or sign_in_administrators(users, proxy=proxy):
        return None
    text = message("serve.team_no_admin")
    return Refusal("team_no_admin", text, message("serve.hint_team_no_admin"))


def _refused(refusal: Refusal, err: TextIO) -> int:
    """Print a refusal to start as a ``validation_error``; return its exit code."""
    return fail(
        err, "validation_error", refusal.text, reason=refusal.reason, hint=refusal.hint
    )


def bind_address(host: str, port: int) -> socket.socket:
    """Listen on ``host:<port>``, an IPv4 or IPv6 address; ``0`` picks a port.

    Raises
    ------
    OSError
        If the port is taken or not allowed, or the address is not one of
        this computer.
    """
    version = ipaddress.ip_address(host).version
    family = socket.AF_INET6 if version == 6 else socket.AF_INET
    # asyncio disables Nagle's algorithm only on connections accepted by an
    # IPPROTO_TCP socket; with it on, a response written in parts waits for
    # the client's delayed acknowledgement (about 40 ms per kept-alive request).
    sock = socket.socket(family, socket.SOCK_STREAM, socket.IPPROTO_TCP)
    try:
        if os.name == "posix":
            # Restart at once even with connections of a stopped server in
            # TIME_WAIT (on Windows this option would allow port sharing).
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen()
    except BaseException:
        sock.close()
        raise
    return sock


def _listening(host: str, port: int) -> str:
    """Return ``host:port`` as an address is written (IPv6 in brackets)."""
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


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
            f'<body><p><a href="{address}">{message("serve.launch_link")}</a></p>'
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


class AppServer:
    """The application on a listening socket, ready to serve.

    Parameters
    ----------
    sock : socket.socket
        Socket from ``bind_address``; the server closes it when it stops.
    app : ASGIApp
        The application.
    url : str
        One-time address of the first session in local mode; the team's
        ``origin`` in team mode.
    launch : LaunchFile or None
        Where ``open_in_browser`` puts the address for the browser; ``None``
        in team mode, which opens no browser.
    access_log : bool
        Write Uvicorn's access log, with ``token=`` values redacted.
    on_stop : Callable[[], None]
        Called as the server starts to stop, before it waits for open
        connections; ends the application's long-lived responses (event
        streams).
    log_level : str, optional
        Level of Uvicorn's own messages (``archiwista.logs.LOG_LEVELS``).
    tls : tuple[Path, Path] or None, optional
        The certificate chain and the private key of TLS in the server (team
        mode); Python's defaults of a TLS server apply (TLS 1.2 or newer).
        ``None`` serves plain HTTP: local mode, or behind a proxy.
    """

    def __init__(
        self,
        sock: socket.socket,
        app: ASGIApp,
        *,
        url: str,
        launch: LaunchFile | None,
        access_log: bool,
        on_stop: Callable[[], None],
        log_level: str = DEFAULT_LOG_LEVEL,
        tls: tuple[Path, Path] | None = None,
    ) -> None:
        self.url = url
        self.launch = launch
        address = sock.getsockname()
        self.port: int = address[1]
        self._socket = sock
        config = uvicorn.Config(
            app,
            host=address[0],
            port=self.port,
            log_config=uvicorn_log_config(log_level),
            access_log=access_log,
            # Archiwista reads forwarded headers itself, from trusted proxies.
            proxy_headers=False,
            server_header=False,
            limit_concurrency=LIMIT_CONCURRENCY,
            ssl_certfile=None if tls is None else tls[0],
            ssl_keyfile=None if tls is None else tls[1],
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


def open_in_browser(server: AppServer) -> None:
    """Open the server's one-time address in the default browser, not waiting.

    The browser gets the ``file:`` address of ``server.launch``, never the
    token itself. A server of team mode has no launch file and opens nothing:
    people open its ``origin`` and sign in.
    """
    if server.launch is None:
        return
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
    log_level: str = DEFAULT_LOG_LEVEL,
    on_ready: Callable[[AppServer], object] | None = None,
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
        Listening address: ``127.0.0.1`` in local mode; in team mode an IP
        address that ``team_refusal`` accepts. A refused one ends the command
        before anything is created or bound.
    port : int or None, optional
        Port; the configured one when omitted, a free one for ``0``.
    access_log : bool, optional
        Write the access log (``token=`` values redacted); off by default.
    log_level : str, optional
        Level of Uvicorn's own messages; ``warning`` unless the command line
        asked for another (``archiwista.logs``).
    on_ready : Callable[[AppServer], object] or None, optional
        Called with the server after the address is printed and before it
        serves, e.g. ``open_in_browser``. The launch file goes once the
        startup token is used, when it expires, and when the server stops.

    Returns
    -------
    int
        ``0`` after a normal stop; else the registry's exit code of what
        went wrong: ``2`` for a refused address and for team mode without an
        administrator who can sign in (``admin_refusal``, checked once the
        state database is open, before the port is bound), ``4`` for a port
        that is taken, and for the settings, the index, the state database,
        the jobs directory or the preview cache that cannot be used the code
        of the error (``2`` invalid settings, ``8``, ``9``).
    """
    try:
        settings = SettingsService(ConfigStore(paths.config_file), registry)
    except SettingsValidationError as error:
        return refuse(
            exception_problem(error, with_detail(message("serve.failed"), str(error))),
            err,
        )
    refusal = team_refusal(settings.get(), host)
    if refusal is not None:
        return _refused(refusal, err)
    try:
        initialize(paths.index_file)
        state = StateStore(paths.state_file)
    except (IndexUnsupportedError, StateError) as error:
        return refuse(
            exception_problem(error, with_detail(message("serve.failed"), str(error))),
            err,
        )
    refusal = admin_refusal(settings.get(), state.users())
    if refusal is not None:
        return _refused(refusal, err)
    if port is None:
        port = settings.get().port
    try:
        sock = bind_address(host, port)
    except OSError as error:
        text = message("serve.port_unavailable", host=host, port=port)
        detail = with_detail(text, error.strerror or str(error))
        return fail(err, "conflict", detail, reason="port_unavailable")
    with sock:
        bound_port: int = sock.getsockname()[1]
        jobs = JobSupervisor(paths, settings)
        try:
            jobs.start()
        except OSError as error:
            return refuse(
                exception_problem(
                    error, with_detail(message("serve.failed"), str(error))
                ),
                err,
            )
        try:
            previews = _start_previews(paths, settings.get().preview_cache_limit_bytes)
        except (OSError, sqlite3.Error) as error:
            jobs.close()
            return refuse(
                exception_problem(
                    error, with_detail(message("serve.failed"), str(error))
                ),
                err,
            )
        unsubscribe = settings.subscribe(
            lambda previous, current: previews.cache.set_limit(
                current.preview_cache_limit_bytes
            )
        )
        scheduler = ScanScheduler(jobs, settings, registry, index_path=paths.index_file)
        # Team mode issues no startup token: people sign in at its origin.
        team = settings.get().team
        origin = team.origin if team.enabled else None
        launch = LaunchFile(paths.data_dir) if origin is None else None
        expiry: threading.Timer | None = None
        if launch is not None:
            expiry = threading.Timer(
                TOKEN_TTL["startup"].total_seconds(), launch.remove
            )
            expiry.daemon = True

        def redeemed(kind: TokenKind) -> None:
            if kind == "startup" and launch is not None:
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
                previews=previews,
                on_redeem=redeemed,
            )
            if origin is None:
                issued = issue_one_time_token(
                    paths.index_file, "startup", minted_by=LOCAL_OWNER
                )
                url = fragment_url(bound_port, issued.token)
                started = message("serve.started", url=url, minutes=_minutes("startup"))
            else:
                url = origin
                listening = _listening(host, bound_port)
                started = message(
                    "serve.started_team", origin=origin, address=listening
                )
            tls = None
            if team.enabled and team.tls_cert is not None and team.tls_key is not None:
                tls = (team.tls_cert, team.tls_key)
            server = AppServer(
                sock,
                app,
                url=url,
                launch=launch,
                access_log=access_log,
                log_level=log_level,
                on_stop=app.state.job_streams.close,
                tls=tls,
            )
            out.write(started + "\n")
            out.flush()
            if expiry is not None:
                expiry.start()
            if on_ready is not None:
                on_ready(server)
            scheduler.start()
            server.run()
        finally:
            if expiry is not None:
                expiry.cancel()
            if launch is not None:
                launch.remove()
            scheduler.stop()
            jobs.close()
            unsubscribe()
            previews.close()
            previews.cache.close()
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
        ``0``, or the registry's exit code when the settings or the index
        cannot be used.
    """
    try:
        settings = ConfigStore(paths.config_file).load()
        initialize(paths.index_file)
    except (SettingsValidationError, IndexUnsupportedError) as error:
        return refuse(
            exception_problem(error, with_detail(message("token.failed"), str(error))),
            err,
        )
    if revoke_all:
        refused = revoke_agent_sessions(paths.index_file)
        out.write(message("token.revoked", count=refused) + "\n")
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
    text = message(
        "token.issued",
        label=issued.label,
        minutes=_minutes("agent"),
        time=expires,
        hours=int(AGENT_SESSION_MAX_AGE.total_seconds()) // 3600,
    )
    err.write(text + "\n")
    return 0


def _minutes(kind: TokenKind) -> int:
    return int(TOKEN_TTL[kind].total_seconds()) // 60


def _start_previews(paths: AppPaths, limit_bytes: int) -> RenderPool:
    """Open and reconcile the preview cache, then start the render pool."""
    cache = PreviewCache(paths.previews_dir, limit_bytes=limit_bytes)
    try:
        cache.reconcile()
        pool = RenderPool(
            workers=default_render_workers(), cache=cache, work_dir=paths.work_dir
        )
        pool.start()
    except BaseException:
        cache.close()
        raise
    return pool
