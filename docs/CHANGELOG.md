# Changelog

Notable changes of Archiwista by release. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the version
numbers follow [SemVer](https://semver.org/). Before v1.0 the HTTP API and the
command-line interface may change.

## [Unreleased]

### Added

- The command of a stored version (A-ADR-049 decision 10, plan P4):
  `archiwista version-command MAGAZYN WERSJA` and `GET
  /stores/{store}/versions/{version}/command` answer the producer's call that selects
  the version again (`producer`, `command`, `options` without the store root) and its
  command line with the store's directory (`line`, `null` for a producer without
  commands). The producer rebuilds it from the version's metadata, offline (Kartograf's
  `command_for_file`, KB-6; IMGWTools' `command_for_version`, IMGW-21); where it cannot,
  the answer is `422 unsupported` with the reason `command_not_rebuildable`, the
  producer's text and a hint (a derived file, for example). The local index keeps each
  answer for the installed version of the producer (table `version_calls`), so the
  producer is asked once. A pin of a project's card carries `command` (`rebuildable`,
  `not_rebuildable` with the producer's text in `command_refusal`, or `unknown` until
  the producer is asked). The source interface gains `VersionCommandAdapter`
  (`command_for_version(version, *, root)`) and `ActionAdapter.run(..., upgrade=)`, the
  update mode a re-pin runs in.
- The jobs over a project's groups (A-ADR-049 decisions 11 and 12, plan P4):
  `archiwista project-verify PROJEKT [GRUPA …]`, `project-check`, `project-repin PROJEKT
  GRUPA` and `project-restore`, and `POST /projects/{project}/jobs` (`kind` `verify`,
  `check`, `repin` or `restore`, `groups` left out for every group), start the job kinds
  `project_verify` (the pinned files hashed in the store, offline: `ok`, `corrupt`,
  `missing`, `content_match` when another version of the slot holds the same content,
  `no_store`), `project_check` (the pins compared with the source by slot and SHA-256:
  `current`, `newer`, `missing`, `removed`, `unverifiable`, `check_failed`,
  `not_checkable`, and the positions without a pin), `project_repin` (one group's calls
  in the producer's update mode; its pins replaced only after a whole success, an
  unchanged pin keeping its time and author) and `project_restore` (the missing pins'
  calls in the default mode: `restored`, `content_match`, `not_restored`,
  `not_restorable`; the project file never written). A local pin's call is the
  producer's command of its version; a version whose command cannot be rebuilt is
  `not_checkable` or `not_restorable` with the producer's text, and its group cannot be
  re-pinned (`422 command_not_rebuildable`). Verifying and checking need to see the
  project; re-pinning and restoring need `project.write` and `store.write`, asked again
  on a retry. One job of a project runs at a time. Pinning what the store holds now
  keeps each version's command in the index at once.
- Pinning versions into a project's groups (A-ADR-049, P3): `archiwista project-pin`,
  `project-unpin`, the routes `POST /projects/{project}/groups`, `…/pins`, `…/unpin` and
  `DELETE …/groups/{group}`, and `jobs start download … --pin PROJEKT --pin-group GRUPA`
  (`POST /jobs` `pin`), which pins what a successful download leaves. In the web:
  "Dodaj do projektu…" in the catalog, the map's coverage and the file card, "Odepnij"
  and "Usuń grupę" on the project's card, and the plan window's option "Dodaj do
  projektu" with the pin's outcome in the download's result.

- A project's exports (A-ADR-049 decision 13): "Eksportuj…" in the section "Zestawy" of
  the project's card, `archiwista project-export PROJEKT NAZWA [--group GRUPA …]` and
  `POST /projects/{project}/exports` write `zestawy/<name>/` in the project directory
  from the pins of every group or of the chosen ones: `pliki.txt`, each pinned
  version's file once, one per line (relative to the export on one share, else
  absolute; for Hydrograf), and `ATRYBUCJE.txt`, each attribution the sources require
  once; UTF-8 with LF, each file replaced whole when written again, never removed. Pins
  whose store is not configured or whose version is not present are left out and
  counted. Writing needs the owner or an administrator and is logged as
  `project.export`. The card's list, `archiwista project-exports PROJEKT` and `GET
  /projects/{project}/exports` say when the project changed after an export
  ("projekt zmieniony po eksporcie — wygeneruj ponownie"). The QGIS project stays v1.1.

- A project's activity (A-ADR-049 decision 14, plan P5): "Aktywność" at the end of the
  project's card, `archiwista project-activity PROJEKT [--limit N] [--cursor ID]` and
  `GET /projects/{project}/activity` (`ProjectActivity`) show what was done to the
  project and its jobs from the action log, newest first: who created, changed,
  shared, pinned, unpinned and exported it, and the jobs started, retried or cancelled
  for it, done or failed; the card the 20 newest and "Więcej" the older ones. For
  whoever sees the project, with the account's name and without the client address or
  the session. The state database moves to schema version 4 (the action log indexed by
  target and by a job's project), migrated on start. The log's action names in the
  web gain "przypięcie wersji" and "odpięcie wersji".

- The user guide (A-ADR-048): "Instrukcja" in the top bar, its icon alone on a phone,
  opens `/instrukcja` in a new tab, a short guide in Polish of twelve slides with
  pictures of this interface: the window and its views, an area and what the store
  holds, the Catalog and the file card, the availability at the source and the plan
  window, downloads in the background and "Zadania", projects, a team server
  (sign-in, account menu, sharing, "Dziennik") and how to report a problem. The slides
  fit a computer's window at 16:9, become one column on a phone and print one a page
  (13.333 × 7.5 in). Like the interface page, the guide and its pictures need no
  session in either mode, so a team server shows it before a sign-in; every other
  rule of a request and the CSP stay as they are.

- The v0.4 acceptance materials: a three-person browser scenario, role/route
  permission matrix, OWASP ASVS evidence checklist and the LAN runbook for
  separate computers and an SMB store. The live LAN run has not yet occurred;
  these materials do not constitute release approval.

- Team mode, its settings and where the server listens (v0.4, ADR-046): the table
  `[team]` of `config.toml` (`enabled`, `origin`, `tls_cert`, `tls_key`,
  `trusted_proxies`, `proxy_user_header`, `proxy_autocreate`) is read when the server
  starts; `GET /settings` does not show it and `PUT /settings` writes it back as it
  was. Two settings of a team that an administrator changes: `network_jobs_per_person`
  (2, from 1 to 10) and `action_log_retention_days` (365, from 30 to 3,650).
  `archiwista serve --host ADDRESS` listens beyond `127.0.0.1` only in team mode, with
  TLS in the server or behind trusted reverse proxies on a specific address; otherwise
  it ends with exit 2, `validation_error` and the reason `host_refused`,
  `tls_required`, `tls_unusable` (files that do not load as a pair, or an encrypted
  key), `proxy_bind_wildcard` or `proxy_bind_not_loopback`, with a hint, before
  anything is created or bound. In team mode it issues no startup token, opens no
  browser and prints the team's address. `archiwista doctor` reports team mode: the
  address, the certificate and key loaded as a pair, a key that other accounts may
  read, the trusted proxies. In team mode every request comes over TLS: with
  `tls_cert` and `tls_key` the server itself serves HTTPS (TLS 1.2 or newer), and
  behind a reverse proxy only a peer of `trusted_proxies` may connect (`403
  forbidden`, `proxy_required`) and its last `X-Forwarded-Proto` must be `https`
  (`403 tls_required`). `Host` and a present `Origin` must be the team's origin,
  every answer carries `Strict-Transport-Security: max-age=31536000`, the session
  cookie is `__Host-archiwista_session` with `Secure`, and `/api/docs` is not
  served. The client address (logs, limits, sessions) is the peer, or behind trusted
  proxies the right-most `X-Forwarded-For` address that is no trusted proxy. Local
  mode is unchanged. USAGE "Team server" shows Caddy and nginx configurations.
- The action log (v0.4, ADR-047) replaces the permission log in the state database
  (state schema 3; the migration keeps every entry, with the outcome `ok`): each entry
  also records the client address, the outcome (`ok`, `denied` or `failed`) and
  details, and a trigger refuses to change an entry. The state database gains a table
  of password hashes, the time before which an account's sessions end, and the
  preferences of each person.
- Passwords of accounts for team mode (v0.4, ADR-046). `archiwista users password ID
  [--temporary] [--stdin]` sets one at the server's terminal (typed twice without
  echo, or one line of standard input), and `POST /users/{user_id}/password` lets an
  administrator give a person a temporary password that the server generates and
  answers once (valid 72 hours, `Cache-Control: no-store`). A password has 12 to
  1,024 characters after NFKC, of any composition, and may not be the account's
  identifier or name or one of the 3,000 most common passwords of 12 characters or
  more (`password_policy` with `details.rule`; the list is derived from SecLists, MIT,
  and ships with its licence and manifest). It is kept as an Argon2id hash
  (`argon2-cffi`, a new dependency; at most two hashes are computed at once), setting
  one ends the account's sessions and logs `user.password_reset`, and `GET /users`
  and `archiwista users list` show each account's password as `none`, `set`,
  `temporary` (with its end) or `expired`, never a hash. `archiwista users disable
  ID` and `users enable ID` switch an account off and on. In team mode the last
  administrator who can sign in cannot be disabled, removed or deprived of the role
  (`409 conflict`, `last_admin`), and `archiwista serve` does not start team mode
  without an enabled administrator who can sign in, with a password that has not
  expired or through the proxy of `proxy_user_header` (exit 2, `team_no_admin`, the
  hint names `archiwista users add ID --role admin` and `archiwista users password
  ID`); `archiwista doctor` names those administrators, reading the state database
  without creating or upgrading it.
- Sessions of team mode (v0.4, ADR-046): a session ends after 8 hours without
  requests and 7 days after its start at the latest (local mode keeps a day without
  requests; an agent's session ends 12 hours after its start in both modes). Setting
  a password or ending an account's sessions also ends the sessions of one-time tokens
  issued before, even when they are exchanged later, and a new session ends the one
  whose cookie the request carried. In team mode `POST /session/tokens` and
  `archiwista token` give addresses of the team's origin.
- Signing in to team mode (v0.4, ADR-046): `GET /session/methods` tells how a session
  starts; `POST /session/login` signs in with an account and its password (an
  unknown account, a wrong password, a disabled account and one without a password
  all answer `401 login_failed` after one password verification; a correct temporary
  password past its end `401 password_expired`; `409 local_mode` in local mode) and
  ends the session whose cookie the request carried. After five failures of an
  account (from any address) or of an address (for any account) each attempt waits,
  1 s doubling up to 15 minutes (`429 rate_limited`, `login_blocked`, `Retry-After`),
  and is refused without verifying a password. A session of a temporary password may
  only read itself, change the password and sign out (`403 password_change_required`).
  `PUT /session/password` changes the person's password (`wrong_password`, the rules
  of `password_policy`), ends every session of the account and its agents' and
  answers a new session. `GET /sessions` lists a person's sessions (`?user=` for an
  administrator) and `DELETE /sessions/{label}` ends one; `DELETE
  /users/{user_id}/sessions` and `archiwista users end-sessions ID` end all of an
  account's, also those of a running server. `GET /session` also tells the name,
  groups, how the session started, `password_change_required` and `team`. `archiwista
  token --user ID` issues an agent's token for an account (required in team mode).
  Sign-ins, failures, signing out, password changes, ended sessions and tokens are in
  the action log. `429` problems of the API carry `details.retry_after_s`. AGENT_API
  section 2 shows a script's sign-in and an agent's token on a team server, and USAGE
  "Team server" signing in, sessions and the wait.
- Signing in through the company's reverse proxy (v0.4, ADR-046): with
  `proxy_user_header`, `POST /session/proxy` signs in as the enabled account that a
  trusted proxy names in that header (trimmed and lower-cased; no password and no
  wait), and `GET /session/methods` answers `proxy: true` for a request that came
  through such a proxy. `proxy_autocreate` creates a missing account without roles
  (`user.add` without an actor). Anything else is `401 login_failed`, logged with the
  reason `unknown_proxy_user` or `disabled`. Every later request of such a session
  must come from a trusted proxy naming the same person, else the session ends. The
  header from any other address is ignored and logged (`session.proxy_header_ignored`,
  once an hour per address). USAGE "Team server" shows Caddy (`forward_auth`,
  `header_up`) and nginx (`auth_request`, `proxy_set_header`).
- The sign-in page of a team server (v0.4, ADR-046): without a session the interface
  asks `GET /session/methods` and, in team mode, shows "Logowanie" instead of the
  local session screen: the account and the password ("Pokaż" shows it; the fields
  carry `autocomplete` for password managers and allow pasting), one message for
  every refused account, the wait after failures counted down from
  `details.retry_after_s`, and "Zaloguj kontem firmowym" when a trusted proxy names
  the person. A temporary password opens "Zmień hasło tymczasowe" before the shell
  (the refusals at their fields: `wrong_password`, `password_policy`, a repeated
  password that differs), and a session that ends leads back to the sign-in.
- The account menu of a team server (v0.4, ADR-046): the person's name in the top bar
  opens the name, the roles and groups of now (the session read again), "Zmień
  hasło…" (left out for a sign-in through the proxy), "Sesje…" (`GET /sessions`:
  each session of the account and its agents with the browser, the address and its
  start or end; "Zakończ" and "Zakończ pozostałe sesje"), "Token dla agenta…" (`POST
  /session/tokens`; the address shown once, with "Kopiuj") and "Wyloguj". Local mode
  keeps the session chip. A request refused because a new session replaced its token
  meanwhile (a password change, a sign-in in another tab) no longer ends the page's
  session.
- "Konta" (accounts) for administrators (v0.4, ADR-046), at the bottom of the
  navigation of a session with the role `admin` only: every account with its roles,
  groups, password state and its end, and state; "Nowe konto" (`POST /users`) opens
  the new account's card, which offers the temporary password first (`POST
  /users/{user_id}/password`, shown once with its end and a copy button). The card
  saves the roles, ends the sessions (`DELETE /users/{user_id}/sessions`), disables
  and enables the account and removes it after a confirmation; `409 last_admin` shows
  at its control. In local mode the passwords and sessions are left out.
- "Grupy" (groups) for administrators (v0.4, ADR-046), beside "Konta": every group
  with its name and members (`GET /groups`, named after `GET /users`); "Nowa grupa"
  (`POST /groups`: the identifier, the name and the members), "Członkowie…" (`PUT
  /groups/{group_id}/members`, a checkbox for every account) and "Usuń…" (`DELETE
  /groups/{group_id}` after a confirmation that its members stop seeing the projects
  shared only with it); a refusal shows in the window that asked.
- Projects of every person (v0.4, ADR-039 erratum 3, A-ADR-029 erratum 2): any
  signed-in person or their agent creates a project where none is yet (`POST
  /projects`, `archiwista project-init`) and the account owns it, at the visibility of
  `default_project_visibility`; the action log records `project.create` with the
  producer and the owner (the computer's owner leaves a project without one). A
  directory with an access entry, an indexed project or a manifest of any producer,
  scanned or not, is a project already: adding a manifest to it needs its owner or an
  administrator. The owner sets the project's data folder too (`PUT
  /projects/{project}/data-dir`), as an absolute subfolder of the project's directory
  after resolving links (`400 validation_error` with the problem
  `own_data_dir_outside_project` otherwise), an administrator anywhere the folder
  rules allow; a change is logged as `project.data_dir`. A person, with their agents,
  has one scan of a data folder waiting or running (`429 rate_limited`,
  `scan_running`) and a folder is asked for once a minute (`scan_too_soon`), both with
  `Retry-After`, a retry too; a waiting scan of the folder is joined, and the
  computer's owner is not limited. `GET /directory` (any session) lists the enabled
  accounts and the groups, with their ids and names, to share a project with.
- The sharing screen of a project (v0.4, SPEC 6.5 r, A-ADR-029 erratum 2):
  "Udostępnij…" on the project card, for its owner and administrators (others see it
  disabled with the reason), opens "Udostępnianie": the owner with "Przekaż…" (give the
  project to another account), who sees it ("wszyscy", "wybrane osoby" and "wybrane
  grupy" with the people and groups of `GET /directory`, "tylko właściciel") and the
  project's data folder (an empty field brings back `dane/`; it was "Zmień folder
  danych…" of "Dane własne", an administrator's). "Zapisz" sends only what changed
  (`PUT /projects/{project}/access`, then `PUT /projects/{project}/data-dir`), shows a
  refusal at its field, and "Dane własne" follows the scan of a new folder. "Nowy
  projekt…" is every person's. Without the role `admin` the Store view's "Odśwież",
  "Pełny skan" and "Uzupełnij obrysy jednostek" and the file card's "Potwierdź bieżącą
  wersję" are disabled with the reason.
- The shared queue (v0.4, ADR-047): a download with a plan claims the positions it
  downloads when it starts, and a download of another person (or another job) that
  planned some of them leaves them to that job: its result lists them as `taken`
  (`path`, `unit`, `job`, `actor`), a notice `taken_by_job` names the job and the
  person ("Pozycje do pobrania (2) pobiera już marek w zadaniu …"), a call all of whose
  positions are taken is skipped (`taken`), and the job ends `partial`, so "Ponów"
  fetches what the other job failed. Claims end with their job. A download without a
  plan of a call a running download runs waits in the queue (notice
  `waiting_for_job`) and then finds the files in the store. The index is rebuilt
  (`SCHEMA_VERSION` 14: `job_claims`), the job protocol is `PROTOCOL_VERSION` 11, and
  a plugin that offers its commands (`ActionAdapter`) also narrows a plan
  (`narrow(plan, paths)`).
- Limits per person in the queue (v0.4, ADR-047): a person, with the jobs of their
  agents, runs at most `network_jobs_per_person` network jobs at once (2 by default;
  the scheduler is no person); further ones wait in the queue and none is refused.
  When a network place frees, the oldest waiting job of the person with the fewest
  running network jobs takes it, and a change of the setting takes effect at once.
  The server's limit of two network jobs stays.
- The view "Zadania" (v0.4, ADR-047; sketch f of SPEC 6.5): the queue and history of
  everyone's background jobs, newest first, with the filters "Wszystkie", "Trwa",
  "Błędy" and "Moje" kept in the address. Each job shows its state, kind and what it
  works on, who started it ("Ty", a person, "… (agent)", "harmonogram"), its progress
  ("3 z 7") or when it ended, why it failed and the positions another download
  fetched for it ("2 pozycje pobiera olga (zadanie …)", also in the list "Pobrania w
  tle"); "Anuluj" for whoever started it and administrators, "Ponów" for a job that
  did not succeed, also one "przerwane" by a restart (disabled with the reason for a
  download without "zapis do magazynu", and for a store's scan, unit outlines or link
  check and the scan of every project's data folder without the role `admin`, as the
  server refuses their retry), "Szczegóły" (its events) and "Dziennik" (the
  end of its log). A job of a project the session does not see shows its kind, "bez
  dostępu", who and its progress only. The list is read every 2 s while a job waits
  or runs, else every 15 s, only while the page is visible, up to the 200 newest
  jobs; the navigation shows the number of running jobs next to "Zadania".
- File download over HTTP (v0.4, ADR-047): `GET /stores/{store}/versions/{version}/file`,
  `GET /projects/{project}/files/{file_id}/file` and `GET
  …/files/{file_id}/snapshots/{label}/file` (also `HEAD`) send the file of a version,
  of an own file and of a snapshot, one file of a set by `?member=` (the new `members`
  of the file card and of each snapshot). Only a file the index knows and the session
  sees, inside its root; streamed with `Range` (`206`), as an attachment with its name
  and the type of its format, `Cache-Control: private, no-store`, never inline (a PDF
  neither). A person streams at most two files at once (`429 rate_limited`,
  `too_many_downloads`, `Retry-After: 10`), and a download from its first byte is
  logged (`file.download` with `size_bytes`). A working file changed since its scan is
  `409 own_file_changed`, one its scan could not read and a snapshot that is not valid
  `409 file_unreadable`, a file gone from the disk `404 missing_file`. An own file and
  a snapshot come only from a data folder that the rules of its scan let be read now:
  one that leads out of its project's directory (a symbolic link put in its place) or
  lies in a store is `409 own_folder_invalid`, and another folder than the one the
  last scan read `409 own_file_changed`. A link of the
  interface passes without `X-Archiwista-CSRF` (`Sec-Fetch-Site` `same-origin` or
  `none`); every other request keeps the header.
- "Pobierz plik" (v0.4, ADR-047): next to a version's title in the file card it saves
  the version's file, in the card of an own file the working file or the snapshot
  chosen on its timeline, and "Pliki zestawu" in the metadata saves each file of a
  Shapefile or a MapInfo TAB by its name: the browser's download of a plain link,
  nothing opens in the browser. It is disabled with the reason while the store is
  unavailable, for a version gone from the store, a working file missing from the disk
  and a snapshot that is not valid. The fix of a document without a preview (PDF, TXT)
  points to it.
- The action log records more (v0.4, A-ADR-047): who started, retried or cancelled a
  job (`job.start`, `job.retry` with `retry_of`, `job.cancel`; the job's kind, store
  and project; a request that joined an active job has `joined`; never the
  scheduler's jobs), changed the settings (`settings.update` with the settings that
  changed, before and after), added or removed a project's task (`project.task_add`,
  `project.task_remove` with `producer` and `task`) and was refused a request
  (`permission.denied`, outcome `denied`, with the refused `action` and the `route`;
  at most one entry per person and action a minute). Jobs started at the command line
  are logged as the local owner's. Every hour, the first time at the server's start,
  entries older than `action_log_retention_days` are deleted and the deletion is
  logged (`log.prune` with `before` and `count`).
- Reading and exporting the action log (v0.4, A-ADR-047), for administrators only
  (`log.read`; a refusal is logged): `GET /log` and `archiwista log list` give a page
  newest first with `total` and `next_cursor`, filtered by `actor`, `action` (a name
  or a group's prefix such as `session.`), `outcome`, `target`, `since` and `until`
  (ISO 8601 with a zone); `GET /log/export` and `archiwista log export` stream every
  entry they select as JSON Lines or CSV (UTF-8 with a BOM; a cell that could start a
  formula begins with `'`), the command to standard output or to `--output` (mode
  `0600`). An export is logged first (`log.export` with its filters, format and
  count) and holds the entries before it.
- The view "Dziennik" (v0.4, A-ADR-047; sketch s of SPEC 6.5), at the bottom of the
  navigation of administrators only (`ViewRoute.admin`; anyone else who opens it gets
  the `403` of `GET /log`): the action log 50 entries a page, newest first, with when,
  who, the action, its target, the outcome and the client's address; the filters
  "Kto", "Działanie" (a group of actions), "Wynik" and the days "Od dnia" and "Do
  dnia" kept in the address; "Dalej" and "Wstecz"; a row opens the state before and
  after, the details, the session and the kind of actor; "Eksportuj CSV" and
  "Eksportuj JSON Lines" save the entries the filters select as a file.
- Preferences and path aliases of each person (v0.4, ADR-047 decision 6 and erratum 1):
  `GET /api/v1/preferences` and `PUT /api/v1/preferences` (any session, its own; an
  agent's are its account's, the computer owner's in local mode) hold `year_types`,
  `basemap` (a configured name, `""` for none, `null` for the first configured one;
  another name is `400 unknown_basemap`) and `path_aliases` (at most 20 pairs of an
  absolute prefix on the server and the same place on the person's computer, each
  at most 400 characters). Every copy path (`CopyPath`: file and version cards,
  station cards, own files, folders and snapshots) gains `personal`, the path through
  the person's first alias that holds it (`null` without one); an alias only changes
  the paths shown and copied, never the paths the routes take. A change is not logged.
- "Moje ścieżki…" in the account menu of a team server (v0.4, ADR-047 decision 6;
  sketch o of SPEC 6.5): the person's path aliases, a prefix on the server ("Na
  serwerze") with the same place on their computer ("U mnie"), at most 20, saved with
  "Zapisz" (`PUT /api/v1/preferences`; the server's refusal is shown). The file card,
  the station card, an own file with its snapshot plan and a project's data folder
  then show the person's path first and copy it; the server's path follows under "Na
  serwerze", the store's aliases as before.
- The comparison of stations: "Porównaj z…" in the toolbar of the station card's chart,
  or up to five rows of the Catalog's station list chosen with their button or `P` and
  then "Porównaj", opens one variable of 2 to 5 stations as panels stacked over one
  time axis (`view=station-compare` with `stations`, `dataset`, `variable`, `from`,
  `to`). Every panel has the same range and interval, so a selection, the wheel or the
  keys in one panel zoom all of them (`Home` or "Cały okres" gives the whole period
  back); a station without the series or the variable keeps its panel with "brak
  danych". Below the panels: the facts of each station as on its card (years with a
  value, label, longest gap, full years, location) and each provider's formula.
  "Zmienna" switches the variable and "Dodaj stację" finds another station of the
  dataset by name, river or code; a sixth station cannot be added. The card keeps the
  chart's range when it opens the comparison. (ADR-045 decision 13, plan I8.6)

- `GET /api/v1/stations/compare` and `archiwista stations compare --station … --station …
  --dataset … --variable …`: one variable of 2 to 5 stations (each
  `<store>/<provider>/<code>`) of one dataset over one range, for display only. The
  range is `from`–`to`, by default every known day of the variable at those stations,
  and every station gets the same interval: its chart is the one `GET
  /stations/{code}/series` gives over that range, its `coverage` the variable's label
  and facts as on its card (in `year_type`), with its location, series version and
  IMGW formula. A station without the series or the variable keeps its place with
  `null` ("brak danych"); no station with the variable is `400 unknown_variable`.
  (ADR-045 decision 12, plan I8.6)

- The chart of the station card, its default tab "Wykres": one or two variables of a
  station's series ("Druga zmienna" on the right axis for another unit), over the
  whole period their labels count (the known days) simplified to the least, mean and
  greatest value of intervals when it has more days than the plot has pixels (with
  the note "wykres uproszczony: … z N dni"), each day's value once a drag selection,
  the wheel or the keys `+`, `-` and the arrows narrow the range (`from`, `to` in the
  address; `Home` or "Cały okres" gives the whole period back). A gap breaks the line
  and is a grey band, never interpolated: the bands are the gaps the coverage label
  counts in the card's year type, so "luki 92%" shows its band. Published extremes
  are dots and an accumulated sum a diamond, each with its date. (ADR-045 and its
  erratum 1, plan I8.5)

- The station card: a click on a station's point on the map, a row of the Catalog's
  list (Enter) or a station's name on its Timeline (`K`) opens it over the view
  (`station=<store>/<provider>/<code>` in the address). It names the station's type,
  river with its hydrographic code, code, provider and state, has the switch "Lata"
  of the Catalog (it renumbers the labels and goes into the address), the location
  with its source, catalog date and uncertainty or why there is none, "Strona stacji
  IMGW" for a water gauge, "Pokaż na mapie", "Kopiuj ścieżkę pliku", the coverage of
  each variable with its full years and longest gap, the tabs "Metadane",
  "Pochodzenie" and "Szczegóły techniczne", and the IMGW formula with "Kopiuj
  atrybucję". `GET /api/v1/stations/{code}` gains `paths`: each series file on this
  computer and as mounted on others. Enter on a row of the station list opens the
  card; `M` shows the station on the map. (ADR-045, plan I8.5)

- `GET /api/v1/stations/{code}/series` and `archiwista stations series CODE --variable …`:
  one or two variables of a station's series as a chart, for display only. Up to
  `max_points` units (2,000 at most) each unit's value; a longer range gives the least,
  mean and greatest value of each interval of `interval` units, `null` without a value
  (never interpolated). `gaps` are the gaps each variable's label counts in
  `year_type` (as on the card; named in the answer) cut at the range's ends and
  `markers` the accumulated sums and the extremes IMGW published with their dates; the
  answer names the series version, the station's file with its SHA-256 and the IMGW
  formula. `dataset` chooses the series (by default the one with every variable),
  `from` and `to` the range (by default the variables' known span, so a label's
  longest gap lies in it), `version` must be the current one (`409` otherwise).
  (ADR-045 and its erratum 1, plan I8.4)

- Plugins: the optional capability `SeriesValuesAdapter` (`archiwista.sources`) reads a
  station's values of a series version for a chart (`read_values`, one `SeriesValues` a
  unit: a missing unit `None`, accumulated sums flagged, the dates of half-year
  extremes) and names, from the producer's registry, the dataset of the half-year
  characteristics and the characteristics that hold a variable's extremes
  (`characteristics_dataset`, `extremes_of`). The IMGW adapter reads with
  `imgwtools.read_series`. (ADR-045, plan I8.4)

- "Oś czasu" of the stations in the Catalog, beside "Lista" (ADR-045, plan I8.3): the
  stations of one dataset with the filters of the list, a row per station with the
  years of one variable ("Wiersz stacji", the map's "Kolor punktów") that expands into
  a row per variable. A year is green when every unit has a value, lighter the fewer
  units have one, a grey hollow box without a value and a grey dashed outline when not
  every unit is known; the headers name the numbering ("r.h. 2024
  (2023.11.01–2024.10.31)", "2024 (kalendarzowy)") and the tooltip gives the year's
  units, the label and the longest gap. Arrows, Home and End move by year and row;
  Enter or Space expands a station.
- `GET /api/v1/stations/timeline` and `archiwista stations timeline --dataset …`: a
  page of the stations of one dataset, each with its series year by year as `GET
  /stations/{code}/coverage` gives it (every year of the range with its units, the
  known ones and those with a value, and its cell), with the filters, order and cursor
  of `GET /stations`; `variable` keeps the stations with a value of each variable and
  only their rows. For a person the command draws a line of year cells per variable
  with its label. A page of 200 water gauges with H, Q and T over 75 years is answered
  within 300 ms (p95). (ADR-045, plan I8.3)
- The Catalog lists the stations of an IMGWTools product (ADR-045, plan I8.2): a row
  per station with a line per variable of its series (the symbol with the fill of its
  coverage, the label and the full years), the code, the river with its hydrographic
  code and the location's source, along rivers or by name ("Wzdłuż rzek", "Nazwa") and
  page by page as the list scrolls. "Bez położenia" is the last group with the reason
  of each station and no way to the map; it starts folded when more than 50 stations
  have a position and open when the map's counter leads to it. The filter panel has
  the fields of `GET /stations` (dataset, kind or meteo types, river code with "z
  dopływami", active, variable, coverage chips with the least full years, range of the
  labels) and "Lata: hydrologiczne / kalendarzowe", which writes `year_type` to the
  address and remembers the choice for the family in the person's preferences.
  "Ukryte przez filtry pokrycia: N" counts what the coverage chips hide. Enter or a
  click shows a located station on the map.
- `GET /api/v1/stations` and `archiwista stations list` take `q` and `sort` (ADR-045, plan
  I8.2). `q` finds a station whose name or river contains the text, whatever the case
  of the letters (`łódź` finds `Łódź`), or whose code begins with it; no character is a
  wildcard. `sort=river`, now the default, lists the stations along rivers (by the
  river's hydrographic code, so a tributary follows its river, then by the station's
  place on the provider's list, then by name); `sort=name` keeps the order by name, the
  only one until now. A cursor belongs to its search and order.
- The year type is remembered for hydro and for meteo data (P15, ADR-045, plan I8.2):
  `year_types` of each person's preferences (`GET /api/v1/preferences`; hydro
  hydrological, meteo calendar by default), changed by `PUT /api/v1/preferences`. The
  station routes and `archiwista stations` (as the computer's owner) number the years
  of a view without `year_type` as remembered for its family; a list of both families,
  without a dataset or a station type, takes the type remembered for hydro data (until
  now each family kept its own default there). A `year_type` in the request wins and
  changes nothing; half-year characteristics stay in hydrological years.
- Stations on the map (ADR-045, plan I8.1). A product of IMGWTools shows its stations in
  place of outlines: the shape says the station type (a triangle for a water gauge, a
  square for a climatological or synoptic station, a circle for a precipitation post),
  the colour and fill the coverage of the "Kolor punktów" variable (green solid, orange
  solid, orange half, grey hollow, grey dashed), and the legend names each. Stations far
  apart at a low zoom form a neutral cluster with its count that zooms in on a click;
  stations at one position spread around it until the next click or `Esc`; above 5,000
  stations the view is a grid. The tooltip gives the name, type, river and the label of
  every variable. The panel has the dataset and station type chips and "Uwzględnij
  stacje na granicy obszaru"; the counter "N bez położenia" opens the Catalog with the
  stations without a position. A browser that cannot draw the map (no WebGL2) still
  shows the counters of the view.
- `GET /api/v1/stations/datasets` and `archiwista stations datasets [--store …]`: the
  datasets with station series in the index, each with the producer's name of its
  segment, provider, family, time unit, default year type, the years of its labels by
  default, the label of its current series version and its variables (key, unit,
  half-year period). `GET /stations`, `GET /map/stations` and `archiwista stations list`
  take the repeatable `meteo_kind` (`synoptic`, `climate`, `precipitation`), and the
  counts follow it. (ADR-045, plan I8.1)
- Downloads run in the background (ADR-043). The plan window is modal only while it
  plans and asks to confirm; once a download starts it floats in a corner and "Zwiń"
  (minimise), "Zamknij" (close) and `Esc` hide or close it without cancelling
  anything, so the map and the other views stay usable. "Pobieranie 2/6 · 45%" in the
  top bar follows the session's downloads (`download`, `project_download`,
  `project_repin`) across views and page reloads (`GET /jobs` for its queued and
  running ones) and opens "Pobrania w tle": each download's progress, notices and files
  or failure, "Anuluj pobieranie" (`POST /jobs/{job}/cancel`, the only way to stop
  one), "Pokaż okno planu" and "Usuń z listy". A toast tells each end, after which the
  map and the step "U źródła" read the store again; the index banner no longer repeats
  a download the top bar shows.
- `scripts/gate.sh` runs ruff format, ruff check, mypy, one pytest call with the
  coverage floor of 80% and the commit check (`scripts/check-commits.sh`: Conventional
  Commits, no AI attribution, author) before every commit; `.editorconfig`,
  `.gitattributes` (LF endings, vendored libraries byte for byte) and `.env.example`.
  (DEV-7.6, DEV-14.1, DEV-4.5)
- GitHub Actions: `.github/workflows/ci.yml` runs the gate on Linux with Python 3.12
  (required) and the newest Python (reported) after installing Chromium, and audits the
  locked PyPI dependencies with `pip-audit` (informative); `live.yml` runs the `live`
  tests weekly; Dependabot updates the pinned actions. Nothing has run yet.
  (DEV-7.7, DEV-10.3, DEV-13.6)
- `SECURITY.md` (private vulnerability reporting, scope); `CONTRIBUTING.md` describes
  `uv sync --locked`, the gate, the CLA and where to report security issues, and
  the pull request template is `.github/PULL_REQUEST_TEMPLATE.md` with the gate
  and CLA checkboxes. (DEV-13.7, DEV-16.2, DEV-16.4)
- `--verbose` (debug) and `--quiet` (errors only) on every command, before or after its
  name, and the variable `ARCHIWISTA_LOG_LEVEL` (`debug`, `info`, `warning`, `error`;
  default `warning`): the log goes to standard error through one handler, the server
  and the job and render processes follow the level, and a variable that names no level
  is a `validation_error`. Uvicorn's start-up lines show only with `--verbose` or
  `ARCHIWISTA_LOG_LEVEL=info`. (DEV-12.2)
- The first-run wizard offers the directory Kartograf and IMGWTools each use when a call
  names no store (`KARTOGRAF_ROOT` or `IMGW_ROOT`, `[kartograf] root` or `[imgw] root` of
  `nogat.toml`, else `<data_dir>/kartograf` or `<data_dir>/imgw`, DEV-19.2) under the
  empty field of that producer, with the button "Użyj tego katalogu", when it exists and
  holds `kartograf-store.json` or `imgw-store.json`. It is only offered: nothing is entered or saved
  until the person clicks and saves, and Archiwista never uses that directory for a call.
  `GET /sources` and `archiwista sources` report it as `default_root` (`path`, `source`
  `default`, `env`, `dotenv` (IMGWTools reads `.env`) or `file`, `name`, `exists`, `marked`, `message`; `null` for a source
  without one); `/health` leaves it out (it is polled; the report is on demand). Kartograf
  and IMGWTools give the root with `store_root()`, which reads no store. `archiwista doctor` prints the root, the layer of the settings that gave it
  and whether it exists and is a store. (DEV-19.2, ADR-033)
- The IMGWTools source behind the extra `archiwista[imgw]`: one plugin, `imgw`, reads a
  store root of IMGWTools for both of its providers, IMGW-PIB and ČHMÚ (archives, series
  and station catalogs as versions, the producer's own problems, the observation register
  of a slot as history), judges the marker `imgw-store.json` and says why it refuses a
  directory (`no_marker` with `imgw store init --root <path>`, `unsupported_marker`,
  `foreign_store`, `not_a_store`). A marker without `created_by` is accepted, as the
  producer accepts it. An incremental scan reads no sidecar of a version the index knows
  (`skip_versions` of `iter_store`), and a file card shows the package and the version
  that wrote the sidecar. `GET /sources` and `archiwista doctor` list the source; without
  the extra it is `not_installed` with `pip install "archiwista[imgw]"` as the fix, and
  Kartograf is unaffected. A store takes an IMGW directory beside or instead of its
  Kartograf one (the next entry). `uv sync --locked --all-extras` installs the extra; CI
  also runs the suite without it. (ADR 0032, DEV-19.12, DEV-19.13)
- A store can name an IMGWTools directory, `imgw` in the settings (`GET` and `PUT
  /settings`, `config.toml`), beside the Kartograf one or instead of it: one of the two
  is required, and a settings file with only `kartograf` loads and saves as before. The
  wizard and the settings offer the field "Katalog IMGWTools" while the source `imgw` is
  available or the store already has such a directory (a saved directory is never dropped
  by a form that cannot offer it). A scan skips the directory of a source that is not
  available, with the notice `source_skipped`, and keeps its entry in the settings: the
  Kartograf directory of the same store is still scanned and probed, and a store whose
  every source is unavailable starts no scan; the notice does not keep a routine scan
  from being forgotten. Files of an IMGW directory are indexed as versions of their
  slots (the entry on the index of IMGW slots below). (SPEC 5.5, 5.8)
- A producer directory that lies inside a store of any producer, or holds one, is refused
  as `root_nested` at its own field: an ancestor of the directory holds `kartograf-store.json`
  or `imgw-store.json`, or a directory up to two levels below it does (no link is
  followed; the producer's own writer looks at the whole tree). Only a new or a moved
  directory is looked around, so an unplugged share does not block other edits. (DEV-19.14)
- The index of an IMGW directory keeps what IMGWTools calls things (`SCHEMA_VERSION` 7:
  an existing index is rebuilt when it is opened and filled by the next full scan, as
  with every schema change). The segment of an archive, a series or a station catalog
  is its dataset, named in Polish from the producer's registry (`Dane hydrologiczne
  dobowe`, `Katalog stacji ČHMÚ`) with the country of its provider and, as its product,
  the family the producer declares for it (`hydro`, `meteo`, `pmaxtp`; `stations` for a
  catalog), so the store view and the Map group the datasets instead of listing them as
  unrecognised segments; a slot keeps the producer's own key
  (`archive:pl.imgw.hydro_daily:2024/codz_2024.zip`) and is named by its file (a catalog
  by its key); a version keeps its provider (`IMGW-PIB`, `CHMI`).
  The observation register of an archive (a source republished the same content under a
  new signal) is kept as the history of its slot (`IndexQueries.observations`) and is
  neither a version, a current version nor part of any count; a record the producer no
  longer lists is forgotten. A producer that lists no segments can describe the ones
  its entries name (`SegmentDescriptionAdapter`). (SPEC 4.3, ADR 0032)
- The index knows the current version of an IMGW slot, which no link names: at the end of
  a scan IMGWTools is asked (`current_version`; the capability `CurrentVersionAdapter`)
  for the slots the scan touched (a version written, back or gone, a problem found or
  resolved) and for those a scan that did not finish left without one; a scan that
  changed nothing asks for none. A slot with a damaged version (an invalid sidecar,
  another schema, a size that differs) has no current version and no older one stands in
  its place: it is `unreadable` with its problem. The catalog and the card show the
  current version and the clean-up report counts only the versions before it as unused.
  A version directory without its sidecar (`missing_sidecar`, a download in progress or an
  interrupted one) is no version and is explained as a non-critical, usually temporary
  problem; a sidecar of another schema (`unknown_schema`) has its own text. (SPEC 4.4,
  4.8.1, ADR 0032)
- A scan of one segment (`segment` of `POST /stores/{store}/scan`) goes only to the data
  source that owns the segment in the index (`IndexQueries.segment_producers`), so a
  Kartograf segment is never offered to the IMGW directory of the same store; a name the
  index does not know goes to the sources that scan by segment, as it did before. IMGWTools
  reads only its whole directory (its dataset is a label), so a job that names a segment
  it owns fails as `unsupported` before anything is scanned. (SPEC 4.4, ADR 0032)
- The index keeps the stations of each provider's current station catalog
  (`SCHEMA_VERSION` 10: an existing index is rebuilt when it is opened and filled by the
  next full scan): after a scan of the whole store the catalog of IMGW-PIB and the one of
  ČHMÚ are read (`read_catalog`; the capability `StationCatalogAdapter`) when their
  current version is not the one the stations came from, and a full scan reads them
  again. Every station is kept, one without a location with the catalog's reason
  (`none`, `zero`, `outside_country`) and no point; a located one is a point of the
  R*Tree `station_points`. A station is its store, provider and code as text, so the
  codes of the two providers never collide, and a new catalog version replaces the
  provider's stations at once. A catalog IMGWTools refuses leaves its provider without
  stations and the scan says so (notice `stations_unreadable`). (SPEC 4.3, 4.4, 4.8.1,
  ADR 0032)
- The index keeps the coverage of each dataset's current series of stations
  (`SCHEMA_VERSION` 11: an existing index is rebuilt when it is opened and filled by the
  next full scan): after a scan of the whole store the `series.json` listing of each
  dataset (`read_series_index`; the capability `SeriesIndexAdapter`) is read when its
  current version is not the one the coverage came from, and a full scan reads every
  listing again; no Parquet file is read. Every variable of every station keeps its
  first and last date with a value, its gaps, its accumulated sums and the station's
  own known periods (ČHMÚ), and each of its years is counted in hydrological and
  calendar years (half-year characteristics: hydrological only) from the gap lists:
  its units, the known ones and those with a value, so a year without a station file
  is unknown, never a gap. A listing IMGWTools refuses leaves its dataset without
  coverage and the scan says so (notice `series_unreadable`). (SPEC 4.3, 4.4, 4.8.4,
  ADR 0032)
- The coverage labels of SPEC 4.8.4 come from the index alone, never from a series file:
  `IndexQueries.station_coverage` gives each variable of a station's series its label
  in a range of years (by default from the dataset's first year to the last published
  one) and a year type (by default hydrological for hydro and calendar for meteo;
  half-year characteristics stay hydrological): "ciągły · 1951–2025", "luki 3% · najdł.
  1981.06.02–1982.12.31" (the share rounded up, "<1%" never "0%"), "częściowy · od 1972
  · luki 12%", "brak danych (tylko H)" and "nieznane", with "· nieznane: 2011–2025" (at
  most two ranges, else "· nieznane: 136 lat"), and the row details: full years, the
  runs of gaps and those over 30 days, the units with a value and the accumulated sums.
  The text is written in the language of the request from the catalog `series.*`.
  (SPEC 4.8.4, A-ADR-021, ADR 0032)
- The stations over HTTP, from the index alone: `GET /stations` pages the stations of
  both providers by name with the filters of SPEC 9.2 (`store`, `provider`, `kind`,
  `active`, `river_code` with `river_scope`, `dataset` (the dataset key), `variable`,
  `coverage` such as `Q:continuous` and `min_complete_years` such as `Q:30`, both
  repeatable and needing `dataset`, `years`, `year_type`, `location`, `limit`,
  `cursor`), in an area (`area_id`, or `bbox` with `bbox_crs`) with the stations on its
  boundary, those closer to it than their location uncertainty
  (`location.on_boundary`; `boundary=false` leaves them out). Each station has its
  location and each series with its version, file, SHA-256, licence and the formula
  IMGW requires, each variable labelled (P16); `counts` has `located`, `boundary`,
  `unlocated` (after the attribute and coverage filters, never placed in an area, SPEC
  4.3 point 3) and `hidden` (the stations a coverage filter hid, which it labels before
  the page is cut). `GET /stations/{code}` is the station's card, `GET
  /stations/{code}/coverage` each variable year by year in R (`full`, `fraction`,
  `none`, `unknown`: the Timeline) and `GET /map/stations` the located stations of a
  map view, with each variable's state and label when `dataset` is given, or their
  grid above `limit`. A code that several stations share (two stores or providers) is
  `400` (`ambiguous_station`, `details.stations`) until `store` and `provider` name
  one. All four answer `503 missing_dependency` (`source_unavailable`) while IMGWTools
  is not available, even when the index holds stations. The archive badge and the
  input archives of the card are not built yet. (SPEC 9.2, 6.7, 6.8, ADR 0032
  decision 13)
- `archiwista stations list` and `archiwista stations show KOD`: the stations and the
  card of one from the command line, with every parameter of `GET /stations` and `GET
  /stations/{code}` as an option of the same name (a repeatable parameter a repeatable
  option: `--coverage Q:continuous --coverage Q:gaps`). With `--json` they print the
  routes' answers, a refusal the routes' problem as the `archiwista-error/1` document
  (exit 6 without IMGWTools); without it, Polish lines for a person: each station with
  the label of every variable of its series and the counters of the whole result, or
  the card with its facts, location, series and licence. (AGENT_API, ADR 0032
  decision 13)
- The projects of IMGWTools: the project directories are searched for
  `imgw-project.json` beside `kartograf-project.json` after a scan of a store with an
  IMGW directory, and a directory with both manifests is one project with the tasks of
  both, each with its producer; its pins name versions of the IMGW index (state, slot,
  label), and `GET /projects/{project}/status` and `archiwista project-status` give
  IMGWTools' check of its manifest (`not_downloaded`, `ok`, `corrupt`, `missing`)
  beside Kartograf's. An invalid manifest of one producer shows that producer's
  message and hides nothing of the other's, and a task name used in both manifests is
  the project problem `duplicate_task`. The Projects view and the store's projects show
  each manifest's store and state, and on a card of two manifests "Manifest
  producenta" chooses the manifest its actions act on. IMGWTools has no project
  actions yet: an action on its manifest is refused (`422`, `no_project_actions`;
  v0.5). (SPEC 4.7, ADR 0032 decision 14)
- The producers' commands as data, for people and agents (ADR-034): `GET /commands` and
  `archiwista commands list` list the commands of every producer whose plugin offers
  them (Kartograf's catalog of `list_commands` and `command_schema`; `producer` keeps
  one) with their options (JSON type, whether required, the allowed values and their
  meanings, the default, bounds, the group of mutually exclusive options and the path
  role of a file path), what a run does (`read_only`, `writes`, `network`, `check`,
  `store`) and example lines, the summary and the description in the language of the
  request. `POST /commands/parse` (`commands parse PRODUCER LINE`) reads a pasted
  command line into a call (`options`, and `run`: the store root and the flags beside
  them), `POST /commands/validate` (`commands validate PRODUCER COMMAND --options JSON
  [--store ID]`) checks a call without the network, a command on a store with the
  directory of a configured store and never with the producer's default root, and `POST
  /commands/format` (`commands format …`) writes the producer's canonical line of a
  call, which parses back into the same call. The producer's refusal keeps its own text
  and hint, with the option in `details.option` (`400 validation_error`,
  `kartograf_error`); Archiwista refuses an option that is a file path (`403
  path_outside_root`), a command outside the catalog (`unknown_command`) and a command
  on a store without its store (`store_required`, `store_without_producer`; `404` for an
  unknown store). A producer whose plugin is missing refuses only its own commands
  (`503 source_unavailable`), one without commands answers `422 unsupported`
  (`no_commands`). Nothing of this uses the network or writes. (SPEC 9.2, SPEC 12
  KB-1 to KB-4, ADR-034)
- The availability at the source, as a background job (ADR-035): the job `availability`
  asks the producer what the source has for a kept area and a product (Kartograf's
  `check_availability` for NMT, NMPT and LAZ in PL and CZ: years, variants, the sheets
  and campaigns a download takes, the land in full sheets) and keeps the report in the
  index as the area's last one (`SCHEMA_VERSION` 8: an existing index is rebuilt when it
  is opened and filled by the next full scan). It needs the network: offline mode refuses
  it before a job exists (`409 conflict`, `offline_mode`). A check of the same area,
  producer and product joins an active one, except that a forced check (asking the source
  again) never waits for an unforced one. Kartograf's metadata cache is Archiwista's own,
  `metadata.db` in `cache/kartograf/` of the data directory, never Kartograf's default;
  the area goes to Kartograf as the envelope of its polygon in EPSG:2180 (EPSG:5514 for
  an area only in CZ), with the country `pl`, `cz` or `auto`. The producer's notices
  become the job's. (SPEC 5.6, 6.3, D5, ADR-035)
- The availability at the source over HTTP and the command line (ADR-035): `POST
  /availability` (`{area_id, product, producer?, force?}`; `archiwista availability check
  AREA --product PRODUCT [--producer ID] [--force]`) answers a kept report younger than
  seven days at once (`200`, the model `AvailabilityInfo`: the area, `checked_at`, the
  job that asked and the producer's report), else starts the `availability` job (`202`
  with `Location: /api/v1/jobs/{job}`; the command runs it in the foreground and then
  prints the report it kept); `force` asks the source even with a fresh report. Offline
  mode refuses a check that needs the source (`409 conflict`, `offline_mode`; exit 4) and
  records nothing, while a fresh report still answers. `GET /availability`
  (`archiwista availability show …`) returns the last report of an area and a product
  without the network, `404` without one. An unknown area is `404`, a producer whose
  plugin is missing `503`, a product the producer does not check `422 unsupported`
  (`no_availability`, the products it checks in `details.allowed`). (SPEC 6.3, 9.2,
  ADR-035)
- The rows of an availability report (SPEC 6.3, 6.4, ADR-010, ADR-017): every
  `AvailabilityInfo` of `GET` and `POST /availability` and of `archiwista availability`
  has `rows`, one per year of each country, with the coverage label of its best variant
  as text in the language of the request ("pełne", "pełne · 2 kampanie", "częściowe ·
  58% · 1 ark. niepełny", "brak danych", with the Polish plural forms) and as structure
  (`coverage`), `other_variants` and the `variants` ranked complete, larger full share,
  fewer campaigns, finer resolution, the report's order; the formats of one set are one
  variant with its default format (ASC, then TIFF) and its size. `store` (`--store`)
  adds the store badge ("pobrane", "pobrane 5/12", "niepobrane") from the index;
  `horizontal`, `resolution` and `vertical_crs` (`--horizontal`, `--resolution`,
  `--vertical-crs`) fix those dimensions, and a year without such a variant is "brak
  danych". The command's text prints a line per year. A store that is not configured is
  `404`. The badge does not tell height systems apart (Kartograf names no store segment
  of a combination; a request in the plan).
- The plan of a download, as a background job (ADR-036): the job `check` asks the
  producer what a run of a command of its catalog would do in a configured store
  (Kartograf's `check_command` with `root=` the store's directory, never its default
  root, and Archiwista's metadata cache): each position with its status (`current`,
  `newer`, `missing`, `unverifiable`, `check_failed`), the labels of the local and of the
  available version, its path below the store root and its size when the producer tells
  it, else `null`, never 0 (Kartograf tells none yet, KC-3). The plan is kept in the index
  with its job (`SCHEMA_VERSION` 9: an existing index is rebuilt when it is opened), and
  the job's result has the counts, the size of the positions to download with
  `size_complete`, the producer's command line of the run (`kartograf … --root …`) and the
  store. It needs the network: offline mode refuses it before a job exists (`409
  conflict`, `offline_mode`). (SPEC 5.6, 6.5, 12.2 KB-5, ADR-036)
- A job may end `partial`: it did part of its work, and its `result` names what failed (a
  plan some of whose positions the source could not tell about: `result.failed`). It is a
  final state with a result and no error; a command following such a job exits 10. A plan
  with none of its positions checked fails the job (`source_unavailable`, reason
  `check_failed`). A client that lists the final states of a job must add `partial`.
  (ERR §1, ADR-036)
- `POST /jobs` starts a job of a command of a producer's catalog on a configured store,
  kind `check` for now (the plan of a run, `202` with the job), and `GET /jobs/{job}/plan`
  returns the plan a `check` job kept (`ActionPlanInfo`: the counts, `todo`, the size or
  `null`, the producer's command line and each position), from the index without the
  network. Before a job exists the request is refused as the job's worker would refuse
  it: a store that is not configured (`404`), a command outside the catalog (`400`,
  `unknown_command`), one on no store or without a check (`422`, `no_store`,
  `no_check`), an option that is a file path (`403`), the producer's refusal of the
  options (`400`, its text) and offline mode (`409`); the job keeps the options as the
  producer read them. `archiwista jobs start check PRODUCENT POLECENIE --store ID
  [--options JSON]` runs the job in the foreground and prints it as it ended (exit 0, 10
  for `partial`), `archiwista jobs plan ZADANIE` prints the plan; `--json` gives the
  route's model. (SPEC 9.2, ADR-036)
- A producer plugin that offers its commands (`ActionAdapter`) also runs them in a store:
  `run(command, options, *, root, plan, on_progress, on_notice)` returns the
  producer-neutral `ActionResult` (`files[]` below the store root with `path`,
  `version_path`, `unit`, `size_bytes`, `sha256`, `label` and `status` `new`,
  `unchanged` or `relabeled`; `items[]` with the code and reason of each unit that
  failed), and `scope(path)` names the segment and the unit a scan reads a file's slot
  by. The Kartograf adapter calls `run_command` with `root=` the store's directory,
  Archiwista's metadata cache and, for the plan of a check, `update="upgrade", plan=…`;
  a plain file (`written`, `replaced`) or one outside the store is `data_error`, reason
  `broken_contract`. (SPEC 12.2 KB-5, ADR-037)
- The download, as a background job (ADR-037): the job `download` runs a command of a
  producer's catalog in a configured store (Kartograf's `run_command` with `root=` the
  store's directory), with `plan_job` the plan a `check` job kept (`update="upgrade"`: only
  its positions to download; one whose source changed since is a failed item,
  `conflict`, `stale_plan`). Its progress events carry the producer's `unit`, `status`
  and `message`, its notices are the producer's, and its result keeps `files[]` and
  `items[]` with the counts of `new`, `unchanged` and `relabeled` files. When it ends the
  index shows the new versions without a scan (the slots of its files are read again);
  cancelled or stopped, it reads the slots of the units it named again first. A run with
  failed units ends `partial`, one with none done fails (reason `run_failed`). A download
  of the call an active download of the store runs starts with the warning notice
  `overlapping_job`. Offline mode refuses it before a job exists. (SPEC 5.6, 12.2 KB-5,
  ADR-037)
- `POST /jobs` starts a download too (`"kind": "download"`, optionally `"plan_job"`: the
  `check` job whose kept plan the run runs), and `archiwista jobs start download PRODUCENT
  POLECENIE --store ID [--options JSON] [--plan ZADANIE]` runs it in the foreground and
  prints the files by status and the units that failed. A download writes the store, so
  it needs the role `store_writer` or the setting `store_write_for_all`: without them a
  session or an agent token (which has the roles of the person who issued it) gets `403`
  (`permission_denied`) and no job is recorded; a plan needs no such permission. A
  `plan_job` the session does not see, or one that kept no plan, is `404`; one of another
  store, command or options is `409` (`plan_mismatch`). (SPEC 9.2, 10.2, SPEC 13 v0.3
  criterion 7, ADR-037)
- Every combination of an availability report has `commands`, the producer's own command
  lines that download it (Kartograf's `download_hint`, without the program name and the
  store), and every variant of a row names them by format (`commands`): `POST
  /commands/parse` reads a line into the call that `POST /jobs` plans and runs, so the
  interface needs no knowledge of a producer's flags. A report kept before reads with no
  commands. `GET /sources` and `archiwista sources --json` list for each producer the
  products whose availability at the source it checks (`availability`). (SPEC 6.3,
  ADR-035)
- `POST` and `GET /session` say whether the session may write the stores now
  (`store_write`: the role `store_writer` or the setting `store_write_for_all`, read at
  each request like `roles`): the permission `POST /jobs` asks of a download, known to a
  client before it asks. (SPEC 9.2, 10.2)
- The map's panel "Wybór" has a fourth step, "U źródła": a product whose availability a
  producer checks (`GET /sources`) and the target store, the area's last report with its
  date (`GET /availability`), "Sprawdź u źródła" and "Sprawdź ponownie" (the
  `availability` job, followed live), and a row per year with its coverage label, its best
  variant (sheet system, resolution, height system, formats, size or "rozmiar nieznany"),
  the store badge and the chip "+N wariantów" that lists the others. "Pobierz…" of a
  variant opens the plan window: each of its lines in the chosen format is read by `POST
  /commands/parse` and planned by a `check` job (no format is chosen for a variant without
  a default one), and the window shows the positions by status, what a run downloads with
  its size ("co najmniej …" when the producer tells only some sizes, "rozmiar nieznany"
  when none, never 0), each position, the positions the producer would refuse to write,
  the store with the producer's directory and each command line to copy. "Pobierz N
  pozycji" starts one `download` per plan (`plan_job`), asks to confirm first above 5 GB
  or 500 positions, and shows the progress, the files by status and the failed units; a
  session without `store_write` sees it disabled with the reason, and offline mode keeps
  the report and disables both actions; without a kept report, offline, the step says it
  cannot ask the source and points to "Stan lokalny", which shows what of the area the
  store holds ("lokalnie 76% obszaru"). A job that ended `partial` shows its summary
  too. (SPEC 6.3, 6.4, 6.5 h, 10.3, UC-02; plan A10, A11)
- Job controls (ADR-038): `POST /jobs/{job}/cancel` cancels a job that waits (at once,
  without a worker) or runs (it ends `cancelled` when its worker has stopped, within the
  stop timeout of 30 s) and answers `202` with the job as it is then; only whoever started
  the job or an administrator may (`403 permission_denied` otherwise, the new permission
  `job.cancel`), and a job that has ended is `409` (`job_finished`). A job another process
  supervises (a server's job cancelled at the terminal, or a terminal's job from the
  interface) is stopped by that process: a request file `<jobs>/<id>.cancel` that each
  supervisor carries out within half a second. `POST /jobs/{job}/retry` starts a job that
  ended `partial`, `failed`, `interrupted` or `cancelled` again as a new job of the session
  with its kind, store and parameters (`202`); one that succeeded or has not ended is `409`
  (`job_succeeded`, `job_active`), and what the kind needs is asked again (a download:
  `store.write`; a snapshot: `project.write`). `GET /jobs/{job}/log` returns the end of the
  job's log (`JobLog`: the last MiB, `truncated`, `size_bytes`); a job without a log is
  `404`, a `preview` job that also builds files of projects the session does not see
  `403`. A job the session does not see is `404` for all three. `archiwista jobs list`
  (the filters of `GET /jobs`), `jobs show`, `jobs cancel`, `jobs retry` (in the
  foreground, as `jobs start`) and `jobs log` give the routes' models with `--json`.
  (SPEC 5.6, 9.2; plan A6)
- Projects created and changed through their producer (ADR-039): `POST /projects`
  (`producer`, `path`, `store`) has the producer write a new project's manifest in a
  project directory of the settings or at most four levels below one, where the next scan
  finds it (`400 project_not_discoverable` in a hidden directory, a store or deeper; `403
  path_outside_root` outside), naming the store's directory of the producer (relative to
  the project directory when the store has path aliases, never the producer's default
  root); the store is configured (`404`), has a directory of the producer (`400
  store_without_producer`) and can be read now (`503 store_unavailable`). Any person
  or their agent creates a new project and owns it (v0.4, above). `POST
  /projects/{project}/tasks` adds a task (a command of the producer's catalog with its
  options, checked without the network: the producer's refusal keeps its text and
  `details.option`, an option that is a file path is `403`) and `DELETE
  /projects/{project}/tasks/{name}` removes one with its pins (its files stay in the
  store), for the project's owner or an administrator (`404` for a project the session
  does not see, `403 permission_denied` for one it may not change). Each answers the
  project's card as the index holds it right after the change (`201` with `Location` for
  a new project); a producer that changes no projects is `422 unsupported`
  (`no_project_actions`). `archiwista project-init PRODUCER DIR --store STORE`,
  `project-add PROJECT NAME COMMAND [--options JSON] [--producer PRODUCER]`,
  `project-remove PROJECT NAME` and `project-status PROJECT` give the routes' models with
  `--json`. (SPEC 4.7, 9.2; plan A7)
- A lock of a project's manifest that stays past the producer's wait (Kartograf's
  `.kartograf-project.lock`, left by a change that was interrupted while it wrote) is
  named: creating a project and adding or removing a task answer `409 conflict` with the
  reason `project_locked`, the lock's path in `details.lock`, the producer's own text and
  the instruction to remove the directory when no program is changing the project.
  Archiwista never removes it. (SPEC 5.6, 14; plan A8, ADR-040)
- The jobs of a project (ADR-040): `POST /projects/{project}/jobs` (`kind` `download`,
  `repin`, `check` or `verify`; optionally `tasks`, every task when left out, exactly one
  for a repin) answers `202` with the job and `Location`. `download` has the producer
  download and pin the tasks not downloaded yet and restore missing pinned versions in
  the configured store the manifest names, `repin` pins one task anew to the source's
  newer versions, `check` compares the pins with the source without effects and
  `verify` checks the pinned files in the store without the network. A download and a
  repin need the project's owner or an administrator and the permission to write the
  stores (`403 permission_denied`, no job); a check and a verification need only to see
  the project, and a project the session does not see is `404`. Refused before a job
  exists: a manifest that names no configured store (`409`, `unknown_store`), a producer
  that runs no project jobs (`422 unsupported`, `no_project_actions`), a second job of
  the project (`409 conflict` naming it) and offline mode for all but `verify` (`409
  offline_mode`). A retry of a project's download or repin asks both permissions again.
  `archiwista project-download PROJECT [TASK ...]`, `project-repin PROJECT TASK`,
  `project-check PROJECT [TASK ...]` and `project-verify PROJECT [TASK ...]` run the job
  in the foreground and print the route's `JobDetail` with `--json` (exit `0`, `10`
  partial, `11` failed, `130`); the interface names the four kinds of jobs. (SPEC 4.7,
  5.6, 9.2, SPEC 13 v0.3 criterion 7; plan A8)
- The job `preview_warm` prepares the first look at current versions ahead (ADR-041):
  the preview pane's thumbnail and the map's tiles at the file's smallest zoom, of the
  versions its filters select (`store`, `product`, `segment`, `project` with its own
  data, `area_id`), in a render process of its own at the lowest CPU priority, within
  the room the preview cache has without evicting previews used in the last week; when
  the room runs out it stops with `stopped: cache_full`, the number of files `skipped`
  and a warning, and ends `partial` (also when a file failed). It never builds a local
  COG (`needs_build` counts the files waiting for one), uses no network and reads the
  stores only; a second warm-up finds the work ready without reading the store. `GET
  /jobs` and `archiwista jobs show` show it; the job protocol is version 9. (SPEC 5.6,
  5.7, SPEC 13 v0.3 criterion 8; plan A9)
- A warm-up of previews on request (ADR-041): `POST /previews/warm` (optional `store`,
  `product`, `segment`, `project`, `area_id`; no body: every store's current versions)
  answers `202` with the `preview_warm` job and `Location`, and `archiwista preview-warm
  [--store] [--product] [--segment] [--project] [--area-id]` runs it in the foreground
  and prints the route's `JobDetail` with `--json` (exit `0`, `10` partial, `11`,
  `130`). Any session may warm; a store that is not configured, a project the session
  does not see and an area the index does not keep are `404` before a job. A project's
  own data is warmed only with `project`, and that job is shown only to those who see
  the project. The setting `preview_warm_after_scan` (off by default) has the scheduler
  warm the versions a store's scan has just indexed, once per scan. (SPEC 5.7, 9.2,
  SPEC 13 v0.3 criterion 8; plan A9)
- Each project of `GET /projects`, of a store's `GET /stores/{store}` and the card of
  `GET /projects/{project}` say whether the session may change the project now
  (`project_write`: its owner or an administrator, read at each request like `roles`):
  the permission adding and removing tasks and a project's download and repin ask, known
  to a client before it asks; `archiwista projects` and `project` print it with
  `--json`. (SPEC 9.2, 10.2; plan A11, A13)
- "U źródła" takes a pasted producer's command ("Wklej polecenie producenta", with or
  without an area; UC-15): the producer is the line's first word when it names an
  installed producer, else the step's; the producer reads the line and checks it without
  the network against the target store, and its text for a mistake shows at the field.
  "Zaplanuj…" opens the plan window for the line (no format to choose), which writes to
  the target store instead of the line's `-o` or `--root`. The plan window offers
  "Dodaj jako zadanie projektu": a project of the producer in that store that the session
  may change and the task's name; it adds the command as the project's task through the
  producer (offline too; a name the producer refuses shows at the name field) and, with
  something to download and the permission to write the stores, starts the project's
  download of the new task, which downloads and pins it ("Dodaj zadanie i pobierz N
  pozycji"). The option is disabled with the reason for a variant of several commands, a
  store without a project of the producer and a session that may change none. A project's
  job in a window shows its tasks by outcome or its files by state, and a failed job its
  instruction (the producer's lock). (SPEC 6.5 h, 10.3, UC-15; plan A11, ADR-042)
- The Projects view acts on projects through their producer (SPEC 6.5 g, UC-06): the list
  has a column "Producent" and "Nowy projekt…" (the producer, a store with its directory
  and the project's directory in a project directory of the settings, `POST /projects`; a
  refusal of the directory or the store shows at its field). The card
  offers "Weryfikuj", "Sprawdź aktualizacje" and "Pobierz" for the project's tasks and
  "Przepnij" at each task (`POST /projects/{project}/jobs`), followed to their end with the
  tasks by outcome or the files by state, the card and "Stan teraz" read again; a job of
  the project that runs already is followed instead. "+ Zadanie" adds a pasted producer's
  command as a task (`POST /commands/parse`, then `POST /projects/{project}/tasks`; the
  producer's text at the line, or at the name for a refused name) and "Usuń" removes a
  task after a question. An action the session may not do is disabled and the card lists
  why: not the project's owner or an administrator (`project_write`), no configured store
  in the manifest, no permission to write the stores (`store_write`), offline mode for a
  check, a download and a repin, a job of the project running. A lock of the manifest that
  an interrupted change left shows with the instruction naming it. The card's line that
  Archiwista only shows a project is gone. (SPEC 6.5 g, 10.2, UC-06; plan A13, ADR-042)
- The acceptance of v0.3 "Actions" (SPEC 13): `tests/e2e/test_acceptance_v03.py` walks
  UC-01 with the stand-in producer and UC-06 over Kartograf's fixture project without the
  network and asserts criteria 3, 4, 5 and 7 on the whole path;
  `tests/integration/test_live_actions.py` (marker `live`, opted in by
  `ARCHIWISTA_LIVE_ACTIONS=1`, run by the author) downloads one NMT sheet through
  Archiwista and through Kartograf's command line and compares the versions, SHA-256,
  sidecars and pins (criterion 1), cancels a project's download after its first sheet
  (criterion 2) and walks UC-01 and UC-06 against GUGiK (criterion 6). The report
  `docs/reports/v0.3-measurements.md` gives criterion 8 (the first thumbnail of a warmed
  version p95 4.1 ms on a local disk) and the evidence of every criterion; USAGE and
  AGENT_API describe 0.3. (SPEC 13 v0.3; plan A14)

### Changed

- Projects are to become Archiwista's own (A-ADR-049; the author's decision of 2026-10-31,
  ECO-054): a project directory will hold `archiwista-project.json`
  (`archiwista-project/1`), written only by Archiwista under its lock
  `.archiwista-project.lock`, with a name, a description, an area in `obszary/`, the store of
  each producer and groups of pinned versions; versions the store holds will be pinned
  without the network from "Stan lokalny", the Catalog and the file card ("Dodaj do
  projektu…"), and the plan window's "Dodaj jako zadanie projektu" becomes "Dodaj do
  projektu"; the project jobs become verify, check, re-pin and restore; the card gets the
  project's activity from the action log, and exports write `pliki.txt` and
  `ATRYBUCJE.txt` (the QGIS export stays v1.1). Kartograf and IMGWTools remove their project
  manifests (`kartograf-project.json`, `imgw-project.json`), which Archiwista will no longer
  read or migrate. SPEC (4.7, 8.4, 9.2, 13 "Projects"), SCOPE and PRD describe it, A-ADR-039
  and A-ADR-040 are superseded, and `docs/plans/2026-10-31-archiwista-projects.md` builds it
  in the phases P2 to P6, released together with v0.3 and v0.4.

- **Breaking:** the producers are re-pinned to their commits without projects (A-ADR-049,
  plan P4): Kartograf `8ad55ab6` and IMGWTools `4bf8bb0d` (`pyproject.toml`, `uv.lock`;
  the supported ranges are unchanged); their project manifests and functions are gone.
  The source interface `archiwista.sources` no longer has `ProjectActionAdapter` and the
  project types `PinnedVersion`, `ProjectTaskRun`, `ProjectRun`, `ProjectFileState`,
  `ProjectFileStatus`, `PROJECT_FILE_STATUSES`, `ProjectCheck`, `TaskOutcome` and
  `TASK_OUTCOMES`: a plugin implements `VersionCommandAdapter` instead. The local index
  is rebuilt (schema 16) by the next scan.

- **Breaking:** projects are Archiwista's own file (A-ADR-049, plan P2): a project is a
  directory holding `archiwista-project.json`, and the producers' manifests
  (`kartograf-project.json`, `imgw-project.json`) are no longer read; a directory with only
  such a manifest is no project. `archiwista project-init KATALOG [--name NAZWA]
  [--description TEKST] [--area-id OBSZAR]` / `POST /projects` (`{"path", "name"?,
  "description"?, "area_id"?}`) write the file (no `producer` and `store` any more: a store
  of a producer is named with `archiwista project-store PROJEKT PRODUCENT --store MAGAZYN` /
  `PUT /projects/{project}/stores/{producer}`); new are `archiwista project-edit` / `PATCH
  /projects/{project}` (name, description) and `archiwista project-area` / `PUT
  /projects/{project}/area` (an area written into `obszary/`, or cleared). Removed: the
  tasks (`project-add`, `project-remove`, `POST`/`DELETE /projects/{project}/tasks`), the
  producers' status (`project-status`, `GET /projects/{project}/status`) and the project
  jobs (`project-download`, `project-repin`, `project-check`, `project-verify`, `POST
  /projects/{project}/jobs`, the job kinds `project_*`). A project and its card carry
  `description`, `state` and `problem` (an invalid file or one of a newer format stays
  listed), `stores`, `area` (its state: `ok`, `missing`, `changed`, `invalid`) and `groups`
  of pinned versions with their pins, instead of `manifests`, `tasks` and `producers`; a
  pin of a slot names its `group` instead of `task`, as does a problem. A change takes the
  lock `.archiwista-project.lock` (`409 project_locked` after 5 s), refuses an invalid or
  newer file (`409 invalid_project_file`, `unsupported_project_schema`), and a directory
  that cannot be written is `500 io_error` (`project_file_write_failed`). The action log
  has `project.update`, `project.area` and `project.store` instead of `project.task_add`
  and `project.task_remove`, and `project.create` names the project's `name` instead of
  the producer. The local index is rebuilt (schema 15): its project files are read again
  by the next scan. `archiwista doctor` no longer names `kartograf-project/1`.

- **Breaking:** the Projects view follows the project file (A-ADR-049, plan P2): the list
  shows each project's description, the store of each producer, its groups, pinned and
  missing versions, and an invalid or newer file with the reason; "Nowy projekt…" asks
  the directory, a name, a description and an optional area file (copied into the
  project's `obszary/`); the card shows the directory, the stores, the area and its
  state, who created the project, its problems and its groups of pinned versions with
  their origin (a plan's commands, or where the versions were chosen) and the state of
  each pin; "Zmień…" changes the name, the description, the area and the store of a
  producer. Gone until the project's jobs come back: "Stan teraz", "Weryfikuj",
  "Sprawdź aktualizacje", "Pobierz", "Przepnij", "+ Zadanie", "Usuń" and the producer
  selector of a project, and the plan window's "Dodaj jako zadanie projektu". The file
  card says "Przypięta w: {project} ({group})"; the Store view lists a project with its
  pinned and missing versions.

- Pinning what the store holds (A-ADR-049 decisions 7 and 8, plan P3): `archiwista
  project-pin PROJEKT GRUPA (--version MAGAZYN:WERSJA … | --query JSON) [--from …]
  [--add]` / `POST /projects/{project}/groups` and `…/groups/{group}/pins` pin named
  versions, older ones too, or the versions of a catalog query into a local group,
  offline from the index (`PinOutcome`: pinned, already pinned, skipped with
  `missing` or `no_sha256`); `archiwista project-unpin PROJEKT GRUPA [--pin
  PRODUCENT:WERSJA …]` / `POST …/groups/{group}/unpin` and `DELETE
  …/groups/{group}` remove pins or a group. The first pin of a producer names the
  project's store; refused are more than 10,000 versions (`too_many_pins`), a taken
  or invalid group name, a group of the plan window, a version of another store
  (`other_store`) and a project store matching no configured one (`unknown_store`).
  The action log has `project.pin` and `project.unpin`.

- A download pins what it leaves into a new project group (A-ADR-049 decision 9, plan
  P3): `POST /jobs` with `"pin": {"project", "group"}` / `archiwista jobs start
  download … --pin PROJEKT --pin-group GRUPA` needs `project.write` of the project
  too and is refused before a job as a new group is (a taken or invalid name,
  `other_store`, `unknown_store`); a retry asks the same. When the job succeeds, its
  worker writes the group after the rescan, origin `plan` with the job's producer and
  calls: every file of the run and, for each call with a kept plan, the current
  version the store holds at each other position. `result.pin` tells what was pinned
  and what was not (`not_in_store`); a job that ends `partial` pins nothing
  (`job_partial`), and a write that fails ends the job `partial`. The job belongs to
  the project in `GET /jobs?project=`, and `job.start` in the log names the project
  and the group.

- **Breaking:** the year types are each person's preference (v0.4, ADR-047 erratum 1):
  `year_types` left `GET` and `PUT /api/v1/settings`, and `PUT
  /api/v1/settings/year-types` is removed; use `PUT /api/v1/preferences`. A
  `year_types` table in `config.toml` is ignored, left out of the file at the next
  change of the settings, and `archiwista doctor` names it as a warning until then.
- The basemap chosen in the map's legend is the person's preference (v0.4, ADR-047
  decision 6): it comes back in every browser the person signs in from, and the
  browser's `localStorage` no longer keeps it. The map asks for no basemap before the
  choice is read.
- **Breaking:** scans of a store, unit outlines and link checks (`POST
  /stores/{store}/scan`, `/footprints`, `/link-check`, and their retry) and a retry of
  the scan of every project's data folder need the role `admin` (the new action
  `store.scan`; `403 permission_denied` otherwise); the scheduler scans on its own.
  (v0.4, A-ADR-029 erratum 2)
- `GET /jobs` lists every job of the queue (v0.4, ADR-047 decision 3): a job only of
  projects the session does not see, left out before, is listed with `hidden: true`
  (a new field of `JobDetail`), its kind, store, who, state, times and progress
  counts, and empty `params`, `session`, `result` and `error`; its own address, its
  events and its log still answer `404`.
- **Breaking:** `archiwista state export` writes `archiwista-state/2`: the password
  hashes (`passwords`), the preferences (`preferences`) and the action log (`actions`,
  instead of `permission_log`), and each account's `sessions_revoked_at`. The copy is
  a secret: the file gets mode `0600`. `archiwista state import` reads `/2` and still
  `/1`, whose log entries become `ok` entries of the action log. (ADR-047)
- A page of stations with the labels of their series is read faster (plan I8.3): the
  years of the page come from the index as plain rows, and a label goes over a
  variable's years once. `GET /api/v1/stations?dataset=…&limit=200` over 200 water gauges
  with H, Q and T of 75 years went from about 255 ms to about 200 ms (median) on the
  development machine. `archiwista stations list --help` no longer says the list is by
  name only.
- Kartograf is pinned at `745e8b18`, and the adapter uses what it asked for (plan, Requests):
  the probe of a store is Kartograf's `store_state(root)`, not a copy of its judgement by file
  name (`adapter/kartograf/marker.py` is gone; ADR-031 erratum 1): the reasons keep their names,
  the parent of a store is now `foreign_store` (Kartograf's `nested_store`) and a directory with
  other files `not_a_store`, a refused marker or nested store carries Kartograf's own text, and
  an unreadable marker is `error`; a task is added with `run_command("project add", …)`, which
  converts a box itself (ADR-039 erratum 2); a lock that stays is recognised by Kartograf's reason
  `project_locked` and the path it gives, no longer by the directory beside the manifest
  (ADR-040 erratum 2).
- **Breaking:** a project is its directory, with the manifest of one producer or of
  both (ADR 0032 decision 14). `GET /projects` items and the card `GET
  /projects/{project}` (and `archiwista projects`, `project … --json`) lose
  `producer`, `store`, `status`, `problem` and `scanned_at`: they are in `manifests`,
  one entry per producer's manifest (`producer`, `store`, `status`, `problem`,
  `scanned_at`), Kartograf's first; every task and pin has `producer`. `GET
  /projects/{project}/status` (`archiwista project-status`) answers `{"project",
  "manifests": [{"producer", "status", "checked_at", "stale", "stale_reason",
  "tasks"}]}`. A change of a task and a project's job act on one manifest: the
  `producer` of `POST /projects/{project}/tasks` and `POST /projects/{project}/jobs`,
  `?producer=` of `DELETE /projects/{project}/tasks/{name}` and `--producer` of
  `project-add`, `project-remove`, `project-download`, `project-repin`,
  `project-check` and `project-verify` name it, else it is the project's only one; a
  project of two manifests refuses a request without it (`400`, `producer_required`),
  and `other_producer` names a producer without a manifest in the project. The
  index keeps one project per directory with its manifests (`SCHEMA_VERSION` 13: an
  existing index is rebuilt when it is opened and filled by the next full scan).
- **Breaking:** a `check` or `download` job takes `calls` (1 to 1000 `{"command",
  "options"}` of one producer) instead of `command` and `options`, so all the lines of a
  report's row, or of a pasted list, are one check and one download (ADR-044): `POST /jobs`,
  `archiwista jobs start RODZAJ PRODUCENT --store ID --call JSON [--call JSON …]`.
  `GET /jobs/{job}/plan` returns the totals and the plan of each call; a refused call is
  named by `details.call`; `plan_job` must have the same calls in the same order (`409
  plan_mismatch`); a call whose check failed is skipped by the download (`not_planned`).
  The plan window starts one check and one download per row, and the top bar shows one
  entry per row. `SCHEMA_VERSION` 12 (the index is rebuilt), `PROTOCOL_VERSION` 10. A row
  of 32 stand-in lines plans in 0.66 s instead of 11.55 s.
- A job worker starts lighter: `archiwista.jobs` loads its names on first use and the
  preview runners import their modules when they run, so a worker imports 51 Archiwista
  modules instead of 83 (0.365 s instead of 0.530 s) (ADR-044, option C).
- The plan of a row of an availability report ("Pobierz…") right after the report asks GUGiK
  nothing: the adapter's `check` opens Archiwista's metadata cache with
  `refresh_ttl_seconds=PLAN_REFRESH_TTL_S` (one hour), and Kartograf `70ef08ef` (ADR-056)
  plans NMT, NMPT and LAZ hints from the index answers the report cached; a report older than
  the hour, the CZ part and every run still ask the source. Kartograf's recorded Kraków
  report: 288 requests for the checks of its 34 hints before, none after, the same positions.
  (ADR-036 erratum 1)
- `GET /map/sheets` items carry `zone`: the PL-2000 zone (5-8) of the powiats the sheet lies
  over, `null` in PL-1992; the `geometry` of a PL-2000 sheet that a zone boundary cuts is its
  part inside its zone (a `Polygon` or `MultiPolygon`). The adapter's `sheet_grid` takes
  Kartograf's `find_sheet_outlines` (Kartograf pinned at `34fab30b`), and `SheetGrid` holds
  the `zones` and the `extents` of the whole sheets; a view is sized by the extent of the
  sheet at its centre, not by its outline.
- The problems of a store, the problems of a file card and the pins of a project name the
  producer they belong to in their fix instructions, not the first producer of the store.
- **Breaking:** errors follow the Nogat error registry. Every problem of the HTTP API has
  the registry's `code` (`validation_error`, `not_found`, `conflict`, `forbidden`,
  `unauthorized`, `missing_dependency`, `store_unavailable`, `data_error`,
  `unsupported`, ...), its HTTP status and the members `type` (the registry page and
  `#<code>`), `title`, `detail` and `hint`,
  `instance`, `details` and `errors[]` with JSON Pointers. The old codes are
  `details.reason` (`session_required`, `csrf_rejected`, `preview_busy`,
  `area_too_large`, ...); the extra members moved into `details` (`job`, `source`,
  `problems`, `layers`, `kartograf`, `preview_reason`, `blocked_by`); the answers `422`
  and `413` are `400`, and `invalid_host` is `403`. The command line prints nothing on
  standard output for an error, ends standard error with the `archiwista-error/1`
  document and exits with the registry's code (2 invalid input, 3 not found, 4
  conflict, 8 store unavailable, 12 forbidden, ...) instead of `1`; a job that does not
  succeed exits `11` (failed) or `130` (cancelled or interrupted), `reindex` of several
  stores `10` when only some were scanned, and `archiwista doctor` `10` or `11` when
  checks fail. The interface sends `Accept-Language: pl` and reads the new members.
  The registry and the Nogat JSON schemas are vendored in `schemas/nogat/`;
  `scripts/generate_errors.py` generates `archiwista._errors`, which a contract test
  compares with the generator's output. `docs/AGENT_API.md` is English and lists the
  codes. (ERR-1 to ERR-6, AGI-6.3, DEV-11.1)
- **Breaking:** the `error` of a job (`GET /jobs/{id}`, `GET /jobs`, the final `state`
  event of the SSE stream) has a code of the error registry, like a problem, and the
  members `detail`, `hint` and `details`. The old job code is `details.reason`
  (`worker_crashed`, `interrupted`, `offline_mode`, `snapshot_blocked`,
  `kartograf_error`, ...): `store_unavailable` stays, a missing or incompatible plugin
  and `own_reader_failed` are `missing_dependency`, `offline_mode`, `snapshot_blocked`,
  `inconsistent_copy` and `target_exists` are `conflict`, `<package>_error`,
  `checksum_mismatch` and `integrity_failed` are `data_error`, `path_outside_root` is
  `forbidden`, `worker_crashed` and `protocol_error` are `internal_error`,
  `interrupted` is `cancelled`; `not_found`, `unsupported` and `cancelled` are as they
  were. The cause of a blocked snapshot is `details.blocked_by`, the member `reason` is
  gone, and a job error of a missing plugin carries `details.source` and a `hint` as the
  problem of a request does. Jobs recorded by 0.2.0 are read with the new codes on
  every read and are not rewritten; the history needs no migration. The command
  line and the interface show the reason where they showed the code. (ERR-1)
- **Breaking:** the texts of errors and answers follow `Accept-Language` (before, `detail`
  and `hint` were Polish always, and `title` alone followed the header). `title`,
  `detail`, `hint`, the texts inside `details`, the `message` of `errors[]` that
  Archiwista's own checks make, and the texts of the answers (the `reason` of a preview,
  the `error` of a job) are English, and Polish when the header prefers Polish; another
  language, a malformed header and no header give English. Every JSON answer under
  `/api/v1`, every problem and every event stream has `Content-Language` and `Vary:
  Accept-Language`. The interface sends `Accept-Language: pl`, so its texts stay Polish.
  The `error` of a job keeps the key and values of its `detail` and `hint`, and renders
  them in the language of the request whenever it is read, in the final `state` event
  too. The command line prints text for a person (the help, the diagnostics, the line
  before an error document) in Polish, and its `--json` answers and the `message` and
  `hint` of the `archiwista-error/1` document in English; the log is English. What is
  written when it happens stays Polish: the `detail` of a store that is not available,
  and the `message` of the notices of a job (deviation AGI-6.4 of `CLAUDE.md`).
  (AGI-6.4, AGI-9.2)
- All documents are English (`docs/CLA.md`, the author's legal text, excepted); the Polish
  interface labels stay in quotes with the English meaning beside them. The README follows
  the order of DOC-2.1 for an app, `docs/PROGRESS.md` has the three sections of the
  standard, `docs/DEVELOPMENT_STANDARDS.md` is gone (the project rules are in `CLAUDE.md`),
  the plans of v0.1 and v0.2 are in `docs/plans/`, ADR-030 is the first decision in
  `docs/decisions/` and `docs/IMGWTOOLS_REQUIREMENTS.md` is removed (IMGWTools 3.0.0 meets
  it; SPEC 12.7 keeps the identifiers). (DEV-2.1, DEV-1.3, DEV-17.4, ECO-005, DOC-2.1,
  DOC-3.1, DOC-6.1, DOC-8.2)
- **Breaking for developers:** the environment is managed by uv. `uv sync --locked`
  replaces the pip installation from `requirements.lock`, which is removed;
  `uv.lock` pins every package with SHA-256 sums at the versions of the 0.2.0
  lock. Development tools are the `dev` dependency group, and the extra `dev` is
  gone. (DEV-6.2, DEV-6.3, DEV-6.5)
- Kartograf is pinned by commit in `pyproject.toml` instead of being installed editable
  from a sibling checkout: `c31ca04c`, the head of its branch `feature/data-output` (the
  data-output convention, ADR-054; the commit is on GitHub). The release pull request
  replaces the commit with the tag. The range of Kartograf versions the adapter reads is
  `SUPPORTED_VERSIONS` in `archiwista.adapter.kartograf`, `>=0.8.0.dev0,<0.9` while the
  commit is pinned, because PEP 440 sorts the development version `0.8.0.dev0` below
  `0.8.0`; the release pull request narrows it to `>=0.8.0,<0.9`. The install command in
  the repair texts is now the pin. (REL-5.3, REL-5.6)
- **Breaking:** the store root of Kartograf is `root` (the data-output convention, DEV §19,
  ECO-051). Archiwista reads the store with the pinned head, whose read API takes `root`
  and whose project manifest `kartograf-project.json` names the store of a project with
  the key `root`: a manifest written by an earlier Kartograf, with `output_dir`, is listed
  as an invalid project with Kartograf's message until Kartograf writes it again. The
  source states `kartograf-store/1` among the schemas it reads. (ECO-051)
- **Breaking:** a Kartograf directory needs its marker, `kartograf-store.json` (DEV-19.12,
  DEV-19.13; ADR-031). A directory that has the layout of a store (a file below a known
  segment) and no marker is refused: the store is `unavailable`, a scan job fails with
  `store_unavailable`, reason `no_marker` and the hint `run once: kartograf store init
  --root <path>`, `PUT /settings` answers `400` with the same reason and hint at
  `stores[n].kartograf`, and `archiwista doctor` prints the command as the fix. Archiwista
  never writes the marker: run the command once for each store an earlier Kartograf wrote.
  It verifies the layout first and refuses a store with stray entries (`invalid_layout`, the
  list is in `details.problems`), which you move out. A marker of another schema, or one
  that is not JSON, is `unsupported_marker`; the root of an IMGW store (`imgw-store.json`)
  is `foreign_store`; a directory whose segments are none of Kartograf's, such as the
  parent of a store, is `not_a_store` and its message asks for the directory that holds
  `kartograf-store.json` instead of the `--output` directory. An empty directory and one
  with known segments and no file stay available: the first download of Kartograf into them
  writes the marker. The generated stores of the tests are marked through
  `kartograf.init_store`. (DEV-19.13)
- The texts for people call the Kartograf directory the store root, the directory that holds
  `kartograf-store.json` and the product directories (usually `data`), and no longer "its
  `--output` directory": the hint of the wizard (its example, `/mnt/nas/kartograf`, no longer
  ends in `/data`), the description of the `kartograf` setting in the OpenAPI document, the
  README, USAGE and the SPEC. The SPEC also has the names of the data-output convention:
  the argument and manifest key `root`, `set_project_root`, the envelope `kartograf-result/1`
  of `run_command` (it has no `cancel` yet), and for IMGWTools `IMGW_REFERENCE_DIR`, the
  statuses `new` and `unchanged` and the marker fields `tool`, `created_at` and
  `producer_version`. (ECO-051)
- The tests find the repository from the test file, never through the installed package,
  so they run against an installed wheel; the generated stores of the tests call the
  directory that holds `data/`, `projects/` and `other-data/` `base`. (REL-2.5)
- `develop` carries the development version `0.3.0.dev0`. (REL-1.1)
- **Breaking for developers:** the package moved from `archiwista/` to
  `src/archiwista/`; import paths and package data are unchanged, and `uv sync
  --locked` reinstalls the editable package. (ECO-011, DEV-5.1)
- Kartograf ships `py.typed`, so mypy checks the calls to it; the code and tests
  that its types rejected are corrected and the `ignore_missing_imports`
  override is gone.
- The interface tests that depend on the browser engine (the panel scrolled by the wheel,
  an upgraded interface reaching the next visit) run in Chromium and in Firefox; install
  both once with `uv run playwright install chromium firefox`.

### Fixed

- The store badge of an availability row ("pobrane", "pobrane 5/12") said "niepobrane"
  for sheets the store held: the report names a combination's campaigns by their survey
  work numbers (Kartograf's `nr_zglosz`), while the index compared them with the
  campaign id of a version's sidecar, the number of the downloaded file
  (`2022-05-10_83233`). A version now counts by its survey work (`survey_work_id` of
  the sidecar, already in the index, so no rebuild is needed). A LAZ tile's sidecar
  names no survey work, so a LAZ combination still shows "niepobrane" until Kartograf
  records it.
- Opening Archiwista from another site showed only "Żądanie wysłane z innej strony
  zostało odrzucone." (`403 csrf_rejected`): behind Cloudflare Access the redirect back
  after signing in at `<team>.cloudflareaccess.com`, and every link to Archiwista
  clicked in an e-mail web client or a chat, since a read was accepted only with
  `Sec-Fetch-Site` `same-origin` or `none`. A `GET` or `HEAD` from another site now
  passes when it is a top-level navigation (`Sec-Fetch-Mode: navigate` and
  `Sec-Fetch-Dest: document` or none) to a path outside `/api/` (the Fetch Metadata
  resource isolation policy); the interface it opens then reads `same-origin`. A frame,
  a subresource, every `/api/*` read (a file link included) and every state change from
  another site are still refused.
- On macOS every request on a kept-alive connection waited about 40 ms for the client's
  delayed acknowledgement: the server relied on asyncio to turn Nagle's algorithm off,
  which it does only on an accepted socket that reports `IPPROTO_TCP`, and one accepted
  on macOS reports `0`. Each connection now sets `TCP_NODELAY` itself, also under TLS in
  the server (team mode).
- After a server upgrade a browser could keep showing the previous interface (the map
  panel without its fourth step "U źródła", so the panel seemed not to scroll down to
  it): the page and the `/static/…` files had only `ETag` and `Last-Modified`, so the
  browser reused its ES modules by heuristic freshness without asking, for days and even
  after a forced reload (Ctrl+Shift+R), which asks again only for the modules of the
  page's start, not for those a view imports later. They now carry `Cache-Control:
  no-cache`: the browser revalidates each file before reuse, a view's modules included,
  and an unchanged one is answered `304`. API responses keep their caching. A browser
  that holds the files of a version before this fix keeps them until their heuristic
  freshness ends (up to a week in Firefox): clear its cached web content once (Firefox:
  Settings → Privacy & Security → Cookies and Site Data → Clear Data… → Cached Web
  Content; Chrome: Delete browsing data → Cached images and files).
- A browser without WebGL2 (such as headless Firefox) showed an empty map and an
  uncaught error: MapLibre throws while it creates the map, past the handler of a failed
  load. The map view and the comparison now say "Mapa nie działa w tej przeglądarce: …"
  with MapLibre's reason.
- A job refused in offline mode said that unit footprints need the network, whatever
  the job was (a check, a download, a project's job); it says that the job needs the
  network.
- The PL-2000 sheet grid ("Siatka godeł") of a view across a zone boundary drew two whole
  grids over each other: Kartograf took the zones as longitude strips and gave every zone's
  sheets over the whole view (19.3-19.7 E x 51.95-52.05 N at 1:2000: 228 + 228 sheets, 862
  pairs of sheets of different zones overlapping). A zone is now the area of its powiats
  (§ 22 of the regulation on the national spatial reference system, Dz.U. 2012 poz. 1247;
  Kartograf ADR-055), and each zone's sheets are drawn only inside it (the same view: 214
  zone-6 and 29 zone-7 sheets, none overlapping).
- A job worker that was interrupted ends itself `STOP_TIMEOUT_S` (30 s) after its first
  interrupt, with the stacks of its threads in the job log, wherever it waits (the
  watchdog of `faulthandler` runs in C). Before, only the supervisor's killer ended a
  worker that did not stop, so one whose supervisor was gone could stay for good: under
  `--cov` an interrupt that lands in coverage's tracer at the wrong moment leaves the
  tracer's lock held, and the worker waits for it in its exit handler.
- Processes that open a new index, state database, preview cache or unit cache of the
  Kartograf adapter at the same moment all open it (the server, the job workers, the
  build processes and the command line share them). SQLite refused the switch of
  `index.sqlite`, `state.sqlite`, `cache.sqlite` or `unit_bboxes.sqlite` to WAL with
  "database is locked" at once, without the busy timeout, in a process that read the
  file's header while another one wrote it, and that process ended at its start; now
  it tries again for up to the busy timeout.
- Archiwista declares `affine>=3,<4`. The previews transform with the `@` operator of
  affine 3; rasterio also admits affine 2, where `@` raises `TypeError`, so in an
  environment that resolved affine 2 every preview was unreadable (Hydrograf caps
  affine below 3, and the environment of the ecosystem's integration run held both).
  A resolver now refuses such an environment.
- The OpenAPI document keeps the `422` problems a route documents itself (`unsupported`
  and `calculation_error` of the preview routes, `unsupported` of `/commands`): only
  FastAPI's own `422` of invalid request data becomes the `400` the API answers.
- At 390 px the bottom navigation of an administrator (nine views since "Zadania" and
  "Dziennik" joined it) was 11 px wider than the screen, so the whole page scrolled
  sideways. The views now share the width equally, with 10 px labels, and a label that
  does not fit is shortened with "…" (in Chromium "Magazyn", "Ustawienia" and
  "Dziennik"); its link keeps the whole name for screen readers.
- On a computer's window shorter than the navigation rail (an administrator's nine
  views need about 490 px below the top bar), the lower views ("Ustawienia", "Konta",
  "Grupy", "Dziennik") lay below the window: the rail had no scrolling of its own, so
  only the whole page could scroll, top bar and view included. The rail now scrolls
  by itself (wheel, touch, `Tab`), without a scrollbar that would narrow its items;
  the page stays in place.
- `Esc` pressed right after opening a station card, file card or own-data card (before
  the card had appeared, e.g. on a busy computer) was lost: the card then opened and its
  address stayed. `Esc` now closes the top card of the address as it is when the key
  comes.
- The English refusal for a missing "write to store" permission quoted the Polish name
  of the permission ("zapis do magazynu"); it now names it in English like the other
  refusals.
- On macOS no file preview, preview build or own-data reading worked: every process
  reading untrusted files was started with an address-space limit (`RLIMIT_AS`), which
  macOS refuses for any value, so the process failed before it ran. The memory limit
  is now set on Linux only; on macOS such a process keeps the inherited limit until the
  macOS port (v1.0, DEV-7.7).
- A render or build process that could not be started (as on macOS before the fix
  above) made a preview request answer `500 internal_error` and a `preview` or
  `preview_warm` job end as `internal_error`. Both now end with `503
  missing_dependency`, reason `renderer_not_started`, with a hint that the cause is in
  the server's log; nothing is remembered about the file, so it previews once a process
  starts. The own-data reader that could not be started for that reason ends with
  `own_reader_failed`, like one that cannot be run at all.
- A render process that crashed without answering (killed by a signal other than the
  system's out-of-memory kill, or ended with an exit status) left its file kept in the
  preview cache as `unreadable` ("The file cannot be read"), so the file never showed
  again, even after the cause was gone, until `previews/` was deleted. A crash is no
  longer the file's verdict: that request answers `unreadable` with the process's
  signal or exit status in `detail`, nothing is kept or remembered, and the next request
  renders the file again. `POST …/preview` (and `archiwista preview REF --build`) now
  reads again a file whose cached answer is `unreadable` or `unsupported_format`, or
  whose probe failed in the last 10 minutes, and replaces the verdict; in the preview
  pane "Sprawdź ponownie" (check again) of a file that cannot be read does that.

### Security

- Security refusals now reach the action log (D7): `request.refused` records
  Host, CSRF, TLS, proxy, session and temporary-password request-rule refusals,
  and paths outside their allowed root. Rejected tokens and missing or refused
  proxy identities record `session.login_failed`. Entries are limited to one
  per actor/client, action and reason per minute; credentials and raw request
  paths, query strings and headers are not stored.
- A project's data folder that lies inside the project's directory (the default
  `dane/` and every folder its owner sets) is checked again at every scan and before
  a snapshot: when a symbolic link now leads it out of the project, nothing in it is
  read and the folder is `invalid` (problem `own_folder_invalid`, its files leave the
  index). Before, a scan followed such a link anywhere the server could read. `PUT
  /projects/{project}/data-dir` saves the folder as its real path, so a link it was
  given through cannot move it later; only an administrator's folder elsewhere lies
  outside the project. (A-ADR-029 erratum 2)
- The previews of an own file and of its snapshots are read only from a data folder
  that the rules of its scan let be read now, as its download is: before, a data folder
  replaced by a symbolic link out of its project after its scan was read through the
  link until the next scan, by its description, thumbnail, tiles, features, members
  and build (`ObjectResolver` checks the folder for every use, the preview cache's
  answers too). Such a file is `409 own_folder_invalid` on every preview route, its
  card has no preview and its layers are `unavailable`; the `preview` and
  `preview_warm` jobs, which check the folder again when they reach the file, fail it
  alone with the code `own_folder_invalid`. A missing folder is `missing_file`, an
  unreadable one `unreadable`, and a project whose data folder is another one than its
  scan read `own_file_changed`.
- A downloaded file is the file that was checked: the answer opens it once, at its
  real path inside its store or data folder and without following a symbolic link
  anywhere on that path, and sends that open file (`HEAD` its size). Before, the
  answer opened the file again by its path after the check, so a file replaced by a
  link right after the check was sent from wherever the link led, e.g. the server's
  state database (review of v0.4, D2). A link put in place since is `403
  path_outside_root`. The render processes of previews check every file of a
  preview the same way before and after each operation: a link put in place since
  is `missing_file`, and nothing is rendered from where it leads.
- Sign-ins sent at once wait like sign-ins one after another: an attempt is admitted
  under the lock of the counts before its password is verified, and one that could
  not start if the attempts under way all failed is `429 login_blocked` with
  `Retry-After: 1`. Before, the wait was checked before the verification and counted
  after it, so 20 or 40 wrong passwords sent together were all verified (review of
  v0.4, D1); now at most five are before the first wait, then one at a time. The
  same holds for the current password of `PUT /session/password`.
- A temporary password cannot become the password that stays: `PUT
  /session/password` refuses a new password equal to the current one, ignoring case
  (`400 password_policy`, `details.rule` `same_as_current`, shown at the new password's
  field), before any hash. Before, a person signed in with a temporary password could
  "change" it to the same value and keep it, though the administrator who issued it
  still knew it (review of v0.4, D3; ASVS 6.4.1).
- A team server opens no session from a one-time token of the computer's owner
  (`local`): a startup token left from a run in local mode, or an agent's token
  `archiwista token` issued without `--user`, is `401 session_required`. Before, such
  a token opened a session with the owner's roles, administrator included, though a
  team has no local owner (review of v0.4, D4; ADR-046 decision 3).
- Every file download that sends the file's first byte is logged (`file.download`):
  the answer decides it as it decides what to send, so a `Range` from byte 0 however
  written (`bytes=00-`, `bytes=1-,0-0`, `bytes=-SIZE`), an `If-Range` that no longer
  matches and more than 100 ranges, which send the whole file, are logged too.
  Before, only a `Range` written `bytes=0-…` counted, so the others streamed the whole
  file unlogged (review of v0.4, D5; ADR-047 decision 5).
- A sign-in with a password whose hash has other parameters than the server's (e.g.
  weaker ones from an earlier argon2-cffi) replaces that hash by one of the current
  parameters; only the hash changes: the password stays temporary with its end, no
  session ends, and a password set meanwhile is not overwritten. Before, the hash was
  kept, though ADR-046 decision 4 and SPEC 10.2 promise the replacement (review of
  v0.4, D8).
- In team mode the last administrator who can sign in (enabled, with a password that
  has not expired, or any enabled one when the proxy names people) cannot be
  disabled, removed or lose the role (`409 last_admin`). Before, any other enabled
  administrator counted, one without a password too, so the only one who could sign
  in could be disabled and nobody could administer the team from the network until
  the next start refused with `team_no_admin` (review of v0.4, D9; ADR-046 erratum 2).
- TLS in the server sets its own floor: TLS 1.2 or newer, and in TLS 1.2 only ciphers
  with ECDHE and AEAD (`security.tls_context`, given to Uvicorn through
  `ssl_context_factory`; the start's check of the files loads the same context).
  Before, the versions and ciphers were the defaults of Python and Uvicorn: TLS 1.2
  accepted CBC ciphers, and an older Uvicorn within the allowed range widened them to
  every TLS 1.0 cipher (review of v0.4, D11; ASVS 12.1.1). Uvicorn's lower bound is
  now 0.54.
- An answer that goes on after its request ends with its session: a job's event
  stream (`GET /jobs/{job}/events`) about a second after the session ended (a
  sign-out, its expiry, the person, an administrator or a password change ending it,
  a revocation of agent sessions) or its account was disabled or removed, and a file
  download (`…/file`) by closing the connection before the file's end. Before, both
  went on to their end (review of v0.4, D6; ASVS 7.4.1, 7.4.2). An event stream also
  ends once its session no longer sees the job.
- A team server makes the stand-in hash of an unknown account as it starts, so the
  first sign-in with a name that has no password costs one verification, as every
  other failed sign-in does. Before, that first sign-in after each start also made
  the hash, so its time told that the name had no password (review of v0.4, D10;
  ADR-046 decision 5).

## [0.2.0] - 2026-10-20

Release "Previews".

Known limitations:

- 30 frames per second or more on the map with 5,000 footprints stays
  unverified without a hardware GPU on the reference computer.
- IMGW data is not yet available in Archiwista (plan v0.5).
- Georeferencing of a rotated JPEG with a world file and differences between
  objects of two snapshots are not part of v0.2.

### Added

- Previews of rasters, vectors, point clouds and ZIP archives; for unsupported
  files the reason and what to do. Thumbnails, tiles and simplified objects
  are built in isolated processes, and the content-addressed cache with an LRU
  limit is kept locally.
- "Fan" (Wachlarz) and "Timeline" (Oś czasu) of local years and campaigns, the
  preview of a whole year from sheets, metadata comparison and the curtain of
  two layers (also cross-fade and side by side).
- Own project data: folder index, files and layers on the map, detection of
  changes since a snapshot, a plan and atomic snapshots of whole files in
  `.wersje/`. Writing a snapshot needs `project.write`; the producer's store
  stays read-only. Jobs that contain project data are visible only to people
  who can access the project.
- API for previews, comparison, layers, own data, plans and snapshots; CLI
  commands `preview`, `compare`, `layers`, `files`, `file`, `snapshot` and
  `own-scan`; the `project` filter in the catalog and in jobs.

### Changed

- WGS84 footprints are polygons instead of rectangular envelopes; map queries
  limit the cost of returning footprints. The index `SCHEMA_VERSION` is 6,
  which **rebuilds the index and runs a full scan on the first start** after
  the update (also on a share that can be disconnected); the permissions
  database stays.
- The default basemap is OpenFreeMap vector tiles in a grey style with Polish
  names of places and waters (exonyms too: Praga, Drezno, Lwów). The second
  option is the GUGiK OSM BaseMap (Poland only); BKG is removed. Old
  configurations keep their own `[[basemaps]]`; to get the new basemaps,
  remove those entries from `config.toml`.
- Test data has footprints inside Poland and Czechia (`34c42ce`).

### Fixed

- Faster map footprints (`5610065`). Security and reliability review
  (`d2d3402`, `f445633`, `48ff701`, `f582d86`, `cde1349`, `ec83b7c`,
  `416dd4f`): isolation of reading and rendering, checks of paths,
  permissions and file changes, consistency of snapshots, limits of the scan
  and error messages that do not reveal other people's data. The state of a
  preview build does not reveal the job of an invisible project; the limits of
  the own-data scan do not mark unvisited files as missing.

## [0.1.0] - 2026-10-19

Release "Browser": the first release, a local browser of the Kartograf store,
read-only. It needs Kartograf 0.8.0 with the public store read API (KA-1 to
KA-6, `docs/SPEC.md` 12.1), at that time from the branch
`feat/archiwista-store-api` of the Kartograf repository (installation:
`README.md`).

Known limitations:

- Local mode only: one person on `127.0.0.1`, no sign-in (team: v0.4).
- No downloads, previews, comparisons, availability checks at the source and
  project changes; they come in v0.2 and v0.3.
- The Kartograf store read API is not yet in a tagged Kartograf release: it
  needs the branch `feat/archiwista-store-api`.
- The smoothness of a map with 5,000 footprints (30 frames per second or more,
  a v0.2 criterion) is not measured on a computer with a GPU; without a GPU
  (software WebGL) it is 8 to 9 frames per second.
- Checked on Linux (Debian 13, Python 3.13); Windows and installation with
  `pipx` or `uv tool` come in v1.0.

### Added

- **Server and first run.** `archiwista serve` on `127.0.0.1` (port 8090 by
  default) prints and opens a one-time session address; the first-run wizard
  asks for Kartograf stores, project folders and offline mode; the "Settings"
  view has the same form.
- **Local index** (SQLite, rebuildable): full and incremental scan of the
  store, refresh of the slots of the selected area, scheduled scans (local
  disk every 5 minutes, share every 15 minutes) and a full control scan every
  24 hours (`full_scan_interval_h`). On a network share the scan reads parts
  of segments in `scan_threads` threads, and the incremental scan does not
  list known version folders. A disconnected share does not clear the index:
  results are marked "from the index of <time>", and the status bar says so.
- **Map:** file footprints and a density grid (more than 5,000 footprints in
  view), an area as a rectangle, polygon, map view, sheet code (typed or
  clicked in the PL-1992 and PL-2000 sheet grids) or a file (GeoJSON,
  GeoPackage, ZIP with a Shapefile); product choice and filters; the local
  state of an area ("83% of the area local") computed in the flat national
  coordinate systems (EPSG:2180, EPSG:5514); the default grey basemap is BKG
  TopPlusOpen.
- **Catalog:** search by sheet code, TERYT, KU, file name, version label,
  request number and the beginning of a SHA-256 (`Ctrl+K` or `/` from every
  view); filters kept in the page address; cursor pagination; location groups
  with counters and a group "without location"; entries of every registered
  source plugin next to the Kartograf entries.
- **File card:** a timeline of all versions with the current one and the full
  sheet (`full_sheet/`), data year told apart from download date, metadata in
  plain words next to the technical values, the licence with copying of the
  attribution, version paths and the standard path to copy (also under other
  drive letters), pins in projects, files of the same producer request, the
  raw sidecar and confirmation of the current version by content.
- **Projects** (preview): `kartograf-project.json` manifests from project
  folders, tasks with the producer's commands, pinned and missing versions,
  the current state from the producer (without network).
- **Store:** state and data source, last scan and last full scan, the
  buttons "Refresh", "Full scan" and "Complete unit footprints", usage by
  product (each version counted once), a report of non-current and unpinned
  versions (nothing is deleted), problems with a repair description, projects
  that use the store.
- **Background jobs** in separate worker processes: scan, unit footprints
  (TERYT, KU: from the network), confirmation of the current version;
  progress through SSE with resuming after `Last-Event-ID`; for a busy store
  `409 conflict` with the running job.
- **HTTP API `/api/v1`:** state (`/health`, `/sources`, `/stores`), catalog
  (`/slots`, `/products`), slot and version cards with the sidecar, request
  files (`/requests/{parent_request}`), map (`/map/footprints`,
  `/map/sheets`), areas and local coverage (`/areas`, `/local-coverage`),
  projects, settings, jobs; RFC 9457 errors with a stable `code` and a Polish
  `detail`; an OpenAPI document with examples and the local `/api/docs`.
- **Command line:** `doctor`, `status`, `sources`, `search`, `entry`,
  `version`, `projects`, `project` with `--json` in the schema of the API
  response, `reindex`, `token` for an agent session.
- **Permissions** (A-ADR-029): a local state database (accounts, groups,
  shares, change log), the roles `admin` and `store_writer`, the project
  visibility `public` / `users` / `group` / `private` in the services, the API
  and the CLI; the commands `users`, `groups`, `share`, `state export` /
  `state import` and their HTTP routes.
- **Source plugins** (A-ADR-024): adapters from the `archiwista.sources` entry
  points, the Kartograf adapter, source states; a missing or incompatible
  producer version is `503 source_unavailable` / `source_incompatible` with a
  repair description, not a server failure.
- Documentation: `docs/USAGE.md` (views), `docs/AGENT_API.md` (scripts and AI
  agents), `docs/reports/v0.1-measurements.md` (measurements and acceptance).
- Performance: the targets of SPEC 4.5 are met on a synthetic store of 50,000
  slots through a real `archiwista serve` (SSD: measured on the release code;
  SMB 3: run 3). First full scan 48.3 s on SSD and 225.6 s on the share;
  incremental scan 12.4 s and 74.7 s; view refresh (p95) 408 ms and 1.83 s;
  list, search and card at most 143 ms (p95, threshold 200 ms), footprints
  198 ms (threshold 300 ms); peak server RSS 168 to 179 MiB with a 256 MB
  index. Method and all figures: `docs/reports/v0.1-measurements.md`.

### Security

- The server refuses to start outside `127.0.0.1`, accepts only the `Host`
  header `127.0.0.1:<port>` or `localhost:<port>` and has no CORS.
- A one-time token in the address fragment (start 10 minutes, agent 5
  minutes; only its SHA-256 in the index); the browser gets the address
  through a private `0600` file, not through the command line.
- The session is an `HttpOnly`, `SameSite=Strict` cookie and a CSRF token in
  the `X-Archiwista-CSRF` header in every `/api` request, reads included;
  rules for `Origin` and `Sec-Fetch-Site`; `DELETE /api/v1/session` ends the
  session.
- Roles and groups are read on every request: taking a role away works at
  once, and a disabled or deleted account ends its sessions; an agent session
  lasts 12 hours at most, and `archiwista token --revoke-all` ends all of them.
- Request body limits (4 KiB token exchange, 1 MiB others, 50 MB area file);
  area files are read in a process with a time limit and without fetching
  coordinate systems from the network.
- Files are opened only under paths from the index in the store roots; a
  project manifest that points outside the project folders is not read.
- CSP computed from the settings, `Referrer-Policy: no-referrer`,
  `X-Content-Type-Options: nosniff`; the interface libraries ship with the
  package (no CDN) with SHA-256 sums checked in tests; `requirements.lock`
  with SHA-256 sums.
- Private local data: a `0700` folder and `umask 077`; `archiwista doctor`
  warns about access by other accounts.
