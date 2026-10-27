# Archiwista API for agents and scripts

A guide for AI agents (for example Claude Code) and scripts that use Archiwista
without a browser. It describes version 0.3 "Actions" (built, not released: the
release is the author's): reading the catalog, previews, layers, comparison, own
data and project snapshots, areas and jobs, and the actions of v0.3: the
producers' commands, availability at the source, plans and downloads into a
configured store, projects created, changed and downloaded through their
producer, job controls and the pre-building of previews. An agent uses the HTTP
API `/api/v1` or the commands `archiwista … --json`; there is no chat tool and
no MCP server.

Until v1.0 the API may change. The full schema with examples is always at
`/api/v1/openapi.json` (it needs a session) and the interactive documentation
at `/api/docs` (it uses the session of an open Archiwista tab). Field names,
parameter names and codes are English; texts for people (`title`, `detail`,
`hint`, `message`) are English, and Polish for the request header
`Accept-Language: pl` (section 7), except the few that are stored in Polish.

## 1. Two ways: the CLI or HTTP

| Need | CLI (`--json`) | HTTP (`/api/v1`) |
|---|---|---|
| state of the server, sources, index and stores | `archiwista status` | `GET /health` |
| producer plugins | `archiwista sources` | `GET /sources` |
| catalog search and filters | `archiwista search [QUERY] [options]` | `GET /slots` |
| card of a file (slot) | `archiwista entry MAGAZYN SLOT` | `GET /stores/{store}/slots/{slot}` |
| card of one version | `archiwista version MAGAZYN WERSJA` | `GET /stores/{store}/versions/{version}` |
| projects | `archiwista projects [--store MAGAZYN]` | `GET /projects` |
| card of a project | `archiwista project PROJEKT` | `GET /projects/{project}` |
| stations of the station catalogs (IMGW-PIB, ČHMÚ) with the coverage of each variable of their series, a page of them year by year (the Timeline), a station's card, a station's series as a chart, a comparison of 2 to 5 stations, and the datasets with station series (the IMGWTools source) | `archiwista stations list [options]` (the parameters of `GET /stations` as options of the same names, a repeatable one repeated), `stations timeline --dataset … [options]` (the same options, `--dataset` required), `stations show KOD [--store …] [--provider …] [--dataset …] [--years …] [--year-type …]`, `stations series KOD --variable … [options]`, `stations compare --station MAGAZYN/DOSTAWCA/KOD --station … --dataset … --variable … [options]`, `stations datasets [--store …]` | `GET /stations`, `GET /stations/timeline`, `GET /stations/{code}`, `GET /stations/{code}/series`, `GET /stations/compare`, `GET /stations/datasets`; `GET /stations/{code}/coverage` and `GET /map/stations` over HTTP only |
| a new project, a task added or removed, the producers' status of a project (v0.3) | `archiwista project-init PRODUCENT KATALOG --store MAGAZYN`, `project-add PROJEKT NAZWA POLECENIE [--options JSON] [--producer PRODUCENT]`, `project-remove PROJEKT NAZWA [--producer PRODUCENT]`, `project-status PROJEKT` | `POST /projects`, `POST /projects/{project}/tasks`, `DELETE /projects/{project}/tasks/{name}[?producer=…]`, `GET /projects/{project}/status` |
| a job of a project's tasks: download and pin, repin one task, check against the source, verify in the store (v0.3) | `archiwista project-download PROJEKT [ZADANIE ...]`, `project-repin PROJEKT ZADANIE`, `project-check PROJEKT [ZADANIE ...]`, `project-verify PROJEKT [ZADANIE ...]`, each with `[--producer PRODUCENT]` (the job in the foreground, printed as it ended) | `POST /projects/{project}/jobs` |
| session token for an agent (for an account: `--user`, required in team mode, v0.4) | `archiwista token [--user ID] --json` | `POST /session/tokens` |
| team mode (v0.4): how a session starts, signing in (with a password or through the company's reverse proxy), changing one's password, a person's sessions, ending all of an account's sessions | `archiwista users end-sessions ID` (the last only) | `GET /session/methods`, `POST /session/login`, `POST /session/proxy`, `PUT /session/password`, `GET /sessions`, `DELETE /sessions/{label}`, `DELETE /users/{user_id}/sessions` |
| area and local state of a product | — (HTTP creates an area; its rows: `search --area-id`) | `POST /areas`, `GET /local-coverage` |
| store scan, SSE | — (HTTP only; an administrator's from v0.4) | `POST /stores/{store}/scan`, `GET /jobs/{job}/events` |
| background jobs: the list, one job, cancel, retry, the end of its log (v0.3) | `archiwista jobs list [--kind …] [--store …] [--state …] [--project …] [--limit N] [--cursor …]`, `jobs show ZADANIE`, `jobs cancel ZADANIE`, `jobs retry ZADANIE` (the new job in the foreground, printed as it ended), `jobs log ZADANIE` | `GET /jobs`, `GET /jobs/{job}`, `POST /jobs/{job}/cancel`, `POST /jobs/{job}/retry`, `GET /jobs/{job}/log` |
| preview and build, optional PNG | `archiwista preview REF [--build] [--output FILE.png]` | `GET`/`POST /stores/{store}/versions/{version}/preview`, `GET …/preview.png` |
| the first look at current versions prepared ahead in the preview cache (pane thumbnail, map tiles at the smallest zoom), optionally of a store, product, segment, project (with its own data) or area (v0.3) | `archiwista preview-warm [--store MAGAZYN] [--product PRODUKT] [--segment SEGMENT] [--project PROJEKT] [--area-id OBSZAR]` (the job in the foreground, printed as it ended) | `POST /previews/warm` |
| comparison of the metadata of two objects | `archiwista compare REF REF` | `GET /compare?a=REF&b=REF` |
| years/campaigns and thumbnail of a layer | `archiwista layers --store ID --product PRODUKT --area-id ID [--thumbnail KLUCZ --output FILE.png]` | `GET /local-layers`, `GET /local-layers/thumbnail.png` |
| files of a project and the card of a file | `archiwista files PROJEKT`, `archiwista file PROJEKT PLIK` | `GET /projects/{project}/files`, `GET …/files/{file_id}` |
| plan and making of a snapshot | `archiwista snapshot PROJEKT PLIK --plan`, `archiwista snapshot PROJEKT PLIK [--note TEKST]` | `GET …/files/{file_id}/snapshot-plan`, `POST …/files/{file_id}/snapshots` |
| scan of the own-data folder | `archiwista own-scan [--project PROJEKT]` | `POST /projects/{project}/scan` |
| producers' commands: the catalog, a pasted line read into a call, a call checked without the network, the line of a call (v0.3) | `archiwista commands list [--producer ID]`, `commands parse PRODUCENT LINIA`, `commands validate PRODUCENT POLECENIE --options JSON [--store MAGAZYN]`, `commands format PRODUCENT POLECENIE --options JSON [--run JSON]` | `GET /commands`, `POST /commands/parse`, `/commands/validate`, `/commands/format` |
| what the source has for an area and a product: the last report kept with its rows (labels, ranked variants, store badges), a check at the source (v0.3) | `archiwista availability show OBSZAR --product PRODUKT [--producer ID] [--store ID] [--horizontal …] [--resolution …] [--vertical-crs …]`, `availability check OBSZAR --product PRODUKT [--producer ID] [--force]` and the same options | `GET /availability`, `POST /availability` |
| a job of a producer's calls on a configured store (all the lines of a row in one job, ADR-044), kind `check` (the plan of a run of each call without its effects) or `download` (the run of each call, with the plans of a `check` job of the same calls if named; it writes the store), and the plans a `check` job kept (v0.3) | `archiwista jobs start check PRODUCENT --store MAGAZYN --call JSON [--call JSON …]`, `jobs start download PRODUCENT --store MAGAZYN --call JSON [--call JSON …] [--plan ZADANIE]` (each `--call` a `{"command": "…", "options": {…}}`; the job in the foreground, printed as it ended), `jobs plan ZADANIE` | `POST /jobs`, `GET /jobs/{job}/plan` |
| a file itself: a version's, an own file's or one file of its set, a snapshot's (v0.4) | — (HTTP only) | `GET /stores/{store}/versions/{version}/file`, `GET /projects/{project}/files/{file_id}/file`, `GET …/files/{file_id}/snapshots/{label}/file` (each also `HEAD`, a set's file by `?member=`) |
| the action log: a page newest first, an export of every entry the filters select (v0.4, administrators) | `archiwista log list [filters] [--limit N] [--cursor ID]`, `log export [filters] [--format jsonl\|csv] [--output FILE]` (section 10) | `GET /log`, `GET /log/export` |

The CLI reads the local index without a running server and calls the same
services as the HTTP routes, as the owner of the local installation
(`LOCAL_OWNER`, roles `admin` and `store_writer`). With `--json`:

- standard output carries nothing but JSON of the route's response schema, the
  same as over HTTP, including the fields `stale` and `stale_stores`; its texts
  are English, as over HTTP without `Accept-Language`;
- an error prints nothing on standard output. The last line of standard error
  is the error document `archiwista-error/1` as compact JSON (section 7), and
  the exit status is the registry's exit code of its `code`: `2` invalid input
  (also a wrong use of the command line, for example a missing argument), `3`
  not found, `4` conflict, `6` missing dependency, `8` store unavailable, `9`
  file system error, `12` forbidden, `13` calculation error, `14` no data, `15`
  not supported; `1` is a defect of Archiwista;
- a job that does not succeed prints its `JobDetail` on standard output and
  exits `11` (it failed) or `130` (it was cancelled or interrupted, also by
  Ctrl+C); `archiwista reindex` of several stores exits `10` when only some
  were scanned; `archiwista doctor` exits `10` or `11` when checks fail. These
  are outcomes, not errors: no error document follows them;
- text for people (diagnostics, the description of an error) always goes to
  standard error, in Polish, and the log, in English, goes there too; none of it
  goes to standard output. Every command takes `--verbose` (debug) or `--quiet`
  (errors only),
  before or after its name, and without them the variable `ARCHIWISTA_LOG_LEVEL`
  (`debug`, `info`, `warning`, `error`) sets the level; the default is `warning`.

Without `--json` the commands print a short Polish text for people; an agent
should always pass `--json`.

The CLI downloads data and writes a store only through a job: a `download` (`jobs
start download`), a project's download or repin (`project-download`,
`project-repin`), or `jobs retry` of one of them. The commands `users`,
`groups`, `share` and `state` (permission administration) are described by
`archiwista --help`. For a team server (v0.4) `archiwista users password ID
[--temporary] [--stdin]` sets an account's password at the server's terminal
(typed twice without echo, or one line of standard input; never an argument,
which other accounts of the computer could read), `users disable ID` and `users
enable ID` switch an account off and on, `users end-sessions ID` ends every
session of the account, also on a running server, and an administrator's session
gives a person a temporary password with `POST /users/{user_id}/password`: the
answer `{"password": "…", "expires_at": "…"}` (72 hours, `Cache-Control:
no-store`) is the only place the password appears. Setting a password ends the
account's sessions; no answer and no log holds a password or its hash (`GET
/users` shows `password`: `none`, `set`, `temporary` or `expired`, and
`password_expires_at`).

## 2. The HTTP session of an agent

The server listens on `127.0.0.1` only (port `8090` by default, the setting
`port`; a team server: below). Every request `/api/*` except the token exchange
(and on a team server `GET /session/methods` and `POST /session/login`) needs a
session.

1. The owner starts the server: `archiwista serve --no-browser`.
2. The agent takes a one-time token: `archiwista token --json` →
   `{"token": "…", "url": "http://127.0.0.1:8090/#token=…", "label": "…", "expires_at": "…"}`.
   The token is valid for 5 minutes and once; the index keeps only its hash.
   The port in `url` comes from the settings (`--port N` changes it), and
   `label` is the label of the session the token opens.
3. The agent exchanges the token for a session: `POST /api/v1/session` with the
   body `{"token": "…"}`. The answer `200` sets the cookie `archiwista_session`
   (`HttpOnly`) and returns `{"actor": "local", "kind": "agent", "roles":
   ["admin", "store_writer"], "store_write": true, "label": "…", "csrf_token":
   "…", "expires_at": "…"}`: `csrf_token` appears only here, `roles` are the
   roles of the actor (an agent has the roles of the person who issued the
   token), and `store_write` says whether the session may write the stores (a
   `download`: the role `store_writer` or the setting `store_write_for_all`).
4. **Every** request to `/api`, `GET` too, carries the session cookie and the
   header `X-Archiwista-CSRF` equal to `csrf_token`; without the header or with
   another token the answer is `403 forbidden` (`details.reason`
   `csrf_rejected`).

An example with `curl` and a cookie jar (`jq` or another JSON parser):

```sh
BASE=http://127.0.0.1:8090/api/v1
JAR="$(mktemp)"            # a file for the current user only
TOKEN="$(archiwista token --json | jq -r .token)"
CSRF="$(curl -sf -c "$JAR" -b "$JAR" -H 'Content-Type: application/json' \
  -d "{\"token\": \"$TOKEN\"}" "$BASE/session" | jq -r .csrf_token)"
H="X-Archiwista-CSRF: $CSRF"

curl -sf -b "$JAR" -H "$H" "$BASE/health"
curl -sf -b "$JAR" -H "$H" -X POST "$BASE/stores/zespol/scan"
curl -sf -b "$JAR" -H "$H" -X DELETE "$BASE/session"   # end of work
```

Rules of the session:

- **No `Origin` header.** `curl`, `httpx` and `requests` do not send it; a
  foreign `Origin` or `Sec-Fetch-Site: cross-site`/`same-site` gets `403
  forbidden` (`csrf_rejected`). The header `Host` must be `127.0.0.1:<port>` or
  `localhost:<port>`, otherwise `403 forbidden` (`invalid_host`). A team server
  (v0.4) answers only its `origin` over HTTPS (`Host` its host, the cookie
  `__Host-archiwista_session`); plain HTTP gets `403 tls_required`, and behind a
  reverse proxy a direct request gets `403 proxy_required`.
- The token goes only in the body of `POST /session`, never in the address
  (`?token=` is rejected).
- The session of an agent acts for the person who issued the token (`actor` in
  jobs is that person's id, `actor_kind` is `agent`, `session` is the label of
  the session), with their **current** roles and project visibility (read at
  every request).
- Sessions live in the memory of the server: they expire after 24 h of
  inactivity (on a team server after 8 h, and 7 days after their start at the
  latest), an agent session 12 h after its start at the latest, and a restart
  of the server ends all of them (`401 unauthorized`, `session_required` → a new
  token). The owner ends all agent sessions with `archiwista token
  --revoke-all`, at once, also on a running server, which also revokes unused
  agent tokens. Disabling or deleting an account ends its sessions, and a
  revoked role stops working at the next request.
- `GET /session` returns the state of the session (without `csrf_token`) with
  the roles and `store_write` read at this request; `DELETE /session` ends it.
  An agent does not issue tokens for further sessions (`POST /session/tokens`
  → `403 forbidden`, `permission_denied`): the owner gives a new token
  (`archiwista token`).
- The body of a request is at most 1 MiB (token exchange: 4 KiB; sign-in: 16
  KiB; area files: 50 MB), otherwise `400 validation_error`
  (`request_too_large`).

**Secrets.** Do not write the token, the cookies, `csrf_token` or the cookie
jar file into prompts, notes, logs, shell history or the repository. Keep them
in process environment variables or in a temporary file readable by you only,
and delete it after the work. The server's logs mask the token of an address
(`token=***`).

### On a team server (v0.4)

A team server (USAGE "Team server") answers only at its `origin` over HTTPS;
`curl` checks its certificate (`--cacert` for the company's authority). `GET
/session/methods`, without a session, answers `{"mode": "team", "password":
true, "proxy": false}` (`"local"` and `false` on one person's computer; `proxy`
is `true` when the request came through a trusted reverse proxy that names a
person).

**An agent** acts for an account, with that account's current roles, through a
one-time token exchanged as in steps 3 and 4: from a person's session (`POST
/session/tokens`) or from the server's terminal with `archiwista token --user ID
--json`. There is no local owner on a team server, so `--user` is required
(exit 2, `user_required`); a disabled account is refused (exit 2,
`user_disabled`), an unknown one is `not_found` (exit 3), and `--revoke-all`
takes no `--user` (`user_with_revoke_all`). `url` is an address of `origin`, and
the cookie is `__Host-archiwista_session`.

**A person's script** signs in with the account and its password: `POST
/session/login` with `{"account": "…", "password": "…"}`. The account is trimmed
and lower-cased, and the password is compared after Unicode NFKC. The answer is
the same as the token exchange's, with `method` `password` and the
`csrf_token`; a session cookie the request carried ends.

```sh
BASE=https://archiwista.firma.local/api/v1
JAR="$(mktemp)"
read -rs PASSWORD          # typed without echo; never an argument or a file
CSRF="$(jq -Rn '{account: "anna.nowak", password: input}' <<<"$PASSWORD" |
  curl -sf -c "$JAR" -b "$JAR" -H 'Content-Type: application/json' \
    --data-binary @- "$BASE/session/login" | jq -r .csrf_token)"
unset PASSWORD
curl -sf -b "$JAR" -H "X-Archiwista-CSRF: $CSRF" "$BASE/session"
```

- `401 unauthorized`, `login_failed`: one answer for an unknown account, a wrong
  password, a disabled account and an account without a password.
  `password_expired`: a correct temporary password past its 72 hours; an
  administrator gives a new one.
- After five failures of one account (from any address) or of one address (for
  any account), each attempt waits 1 s, then 2 s, 4 s… up to 15 minutes: `429
  rate_limited`, `login_blocked`, with `Retry-After` and `details.retry_after_s`.
  No password is checked during the wait, so retrying earlier gains nothing; a
  success clears both counts.
- `password_change_required: true` (a temporary password): until `PUT
  /session/password` with `{"current_password": "…", "new_password": "…"}` the
  session may only call `GET /session`, `GET /session/methods`, that route and
  `DELETE /session`; anything else is `403 forbidden`,
  `password_change_required`.
- `PUT /session/password` answers a new session (a new cookie and a new
  `csrf_token`) and ends every other session of the account and of its agents.
  It refuses a new password that breaks a rule (`400 password_policy`), a wrong
  current one (`403 wrong_password`, which counts as a failed sign-in), an
  agent's session (`403 permission_denied`) and a session of the reverse proxy
  (`409 proxy_session`).
- `GET /sessions` lists the live sessions of the person and of their agents,
  oldest first (`label`, `kind` `browser` or `agent`, `method`, `client`,
  `user_agent`, `created_at`, `last_seen_at`, `expires_at`, `current`); `DELETE
  /sessions/{label}` ends one (another person's label is `404`). An
  administrator lists another account's with `?user=ID` and ends any session;
  `DELETE /users/{user_id}/sessions` and `archiwista users end-sessions ID` end
  every session of the account, also the tokens it issued and nobody exchanged
  yet.
- On a local server `POST /session/login`, `POST /session/proxy` and `PUT
  /session/password` are `409 conflict`, `local_mode`.

**Behind the company's reverse proxy** (`proxy_user_header`), a request that came
through it signs in as the person it names with `POST /session/proxy` (no body,
no password, no wait): the same answer with `method` `proxy`. Every later request
of that session must come through the proxy naming the same person, else the
session ends (`401 session_required`). A name that is no enabled account is `401
login_failed` (with `proxy_autocreate` a missing account is created without roles),
and so is a request that did not come through a trusted proxy.

**Sharing a project.** `GET /directory` (any session) lists the enabled
accounts and the groups, each with its `id` and `name`, to choose from for
`PUT /projects/{project}/access`; `GET /users` and `GET /groups` stay an
administrator's. A person or their agent creates projects and owns them,
gives one a data folder inside its directory, and scans the folders of the
projects they see within their limits (section 9); scans of a store, unit
outlines and link checks are an administrator's (`403 permission_denied`).

## 3. Search and filters (`GET /slots`, `archiwista search`)

Every parameter of `/slots` has an option of the same name in `archiwista
search` (underscore → hyphen); `q` is the positional argument `QUERY`. The
same model checks the values, so the errors are identical.

| Parameter | CLI option | Meaning |
|---|---|---|
| `q` | `QUERY` | text; every word must match: sheet code, TERYT, KU, file name, segment and product, version label, job request number, campaign, edition (word prefix, no Polish diacritics); a word of 8–64 hexadecimal digits also matches the start of a SHA-256 |
| `store` | `--store` | store id (`/stores`); an unknown one → `400` |
| `product` | `--product` | product (`/products`), for example `nmt` |
| `country` | `--country` | country code, for example `PL` |
| `years` | `--years` | year of the data (not of the download): `2023`, `2020-2023`, `2020-`, `-2023` |
| `unit` | `--unit` | exact unit code: sheet code, TERYT, KU |
| `location` | `--location` | `any` (default), `with` (outline or the whole country), `none` (no location) |
| `versions` | `--versions` | `current` (default), `all`, `full_sheet`, `pinned`, `noncurrent_unpinned` |
| `status` | `--status` | `ok`, `missing`, `no_sidecar`, `unreadable`, `unrecognized` |
| `area_id` | `--area-id` | an area kept by `POST /areas` (not together with `bbox`) |
| `bbox` | `--bbox` | rectangle `min_x,min_y,max_x,max_y` in the CRS `bbox_crs` |
| `bbox_crs` | `--bbox-crs` | CRS of `bbox`, `EPSG:4326` by default; another one is converted by the producer's pinned operation |
| `limit` | `--limit` | rows per page: 1–200, 50 by default |
| `project` | `--project` | versions pinned in a visible project; an invisible project → `404` |
| `cursor` | `--cursor` | `next_cursor` of the previous page of the same query |

Give values that start with a minus with `=`:
`archiwista search --bbox=-10,40,0,45 --json`.

```sh
archiwista search N-34-130-D-d-2-4 --json
archiwista search --product=nmt --years=2020-2023 --versions=all --limit=200 --json
curl -sf -b "$JAR" -H "$H" "$BASE/slots?product=nmt&years=2020-2023&versions=all&limit=200"
curl -sf -b "$JAR" -H "$H" "$BASE/slots?bbox=19.9,50.0,20.0,50.05&location=with"
```

The answer (`CatalogPage`, abridged):

```json
{
  "items": [
    {
      "store": "zespol",
      "slot": "nmt/pl_1992_1m_evrf2007/N-34/130/D/d/2/4/N-34-130-D-d-2-4.asc",
      "name": "N-34-130-D-d-2-4.asc",
      "unit": "N-34-130-D-d-2-4",
      "product": "nmt",
      "country": "PL",
      "status": "ok",
      "location": {"kind": "footprint", "reason": null, "source": "sheet"},
      "version": {"path": "nmt/pl_1992_1m_evrf2007/versions/…/N-34-130-D-d-2-4.asc",
                  "label": "2025-04-26_82710", "data_year": 2025,
                  "is_current": true, "is_full_sheet": true, "…": "…"},
      "versions_count": 1
    }
  ],
  "next_cursor": null,
  "groups": {"footprint": 1, "country": 0, "none": 0},
  "stale": false,
  "stale_stores": []
}
```

`groups` counts the location groups in the **whole** result (all pages),
whatever `location` is chosen. Rows without a location have no outline and do
not appear on the map (`GET /map/footprints`), but they are in the catalog.

## 4. Paging

The cursor is opaque and bound to its query: fetch the next pages with the
**same** filters and `cursor=<next_cursor>` until `next_cursor` is `null`. The
cursor of another query, a `limit` outside 1–200 or an unknown parameter give
`400 validation_error`. Pages of any size together hold the same rows in the
same order (file name, slot, store).

```sh
cursor=""
while :; do
  page="$(archiwista search --versions=all --limit=200 ${cursor:+--cursor="$cursor"} --json)"
  printf '%s\n' "$page" | jq -c '.items[] | {store, slot, version: .version.path}'
  cursor="$(printf '%s' "$page" | jq -r '.next_cursor // empty')"
  [ -n "$cursor" ] || break
done
```

The same over HTTP: `"$BASE/slots?versions=all&limit=200&cursor=$cursor"` (the
cursor is safe in a URL).

## 5. Cards, state and freshness

- `archiwista entry MAGAZYN SLOT` / `GET /stores/{store}/slots/{slot}`: the card
  of a file (`SlotCard`): all versions, `current` and `full_sheet`, the pins of
  visible projects (`pinned_by`), problems with a repair instruction and
  `paths` (`local` is the path on this computer, `aliases` the same path under
  other drive letters).
- `archiwista version MAGAZYN WERSJA` /
  `GET /stores/{store}/versions/{version}`: all values of the version from the
  index, the outline in WGS84 and the raw sidecar; the sidecar alone:
  `GET …/versions/{version}/sidecar`.
- `GET /requests/{parent_request}`: the files of one producer request (for
  example both sides of the PL/CZ border).
- `archiwista projects` / `GET /projects` and `archiwista project PROJEKT` /
  `GET /projects/{project}`: the projects visible to the actor; a hidden project
  answers like a missing one (`404`). A project is its directory, which holds
  the manifest of Kartograf (`kartograf-project.json`), of IMGWTools
  (`imgw-project.json`) or both: `manifests` lists each producer's manifest,
  Kartograf's first, with the configured `store` it names (`null`: none),
  its `status` when it was read, the producer's `problem` with an invalid one
  (whose tasks are not read; the other manifest is) and `scanned_at`. Tasks and
  pins carry the `producer` of their manifest; a task name in both manifests
  is the problem `duplicate_task`. `--store` / `?store=` lists the projects
  with a manifest naming the store. Each project says whether the actor may
  change it now (`project_write`: its owner or an administrator; read at each
  request), as the project's changes and jobs below decide it. `archiwista
  project-status PROJEKT` / `GET /projects/{project}/status` asks each
  manifest's producer for the state now (no network): `manifests` with each
  task's state, `stale` with the last scan's state while that manifest's store
  is unavailable; the first refusal of a producer is the answer.
- `archiwista project-init PRODUCENT KATALOG --store MAGAZYN` / `POST /projects`
  (`{"producer", "path", "store"}`), `archiwista project-add PROJEKT NAZWA
  POLECENIE [--options JSON] [--producer PRODUCENT]` / `POST
  /projects/{project}/tasks` (`{"name", "command", "options"}`, optionally
  `"producer"`) and `archiwista project-remove PROJEKT NAZWA [--producer
  PRODUCENT]` / `DELETE /projects/{project}/tasks/{name}` (optionally
  `?producer=`) (v0.3, ADR-039): the producer writes its manifest, and the
  answer is the project's card as the index holds it at once (`201` with
  `Location` for a new project, `201` for a task, `200` for a removal). A new
  project lies in a project directory of the settings or at most four levels
  below one, outside hidden directories and stores (`400
  project_not_discoverable`; elsewhere `403 path_outside_root`), and names a
  configured store (`404`) with a directory of the producer (`400
  store_without_producer`) that can be read now (`503 store_unavailable`).
  Where no project is yet, any person or their agent creates one (v0.4) and
  the account owns it, at the visibility of the setting
  `default_project_visibility` (`project.create` in the action log); the
  computer's owner (`project-init`, local mode) leaves it without an owner. A
  directory that is a project already (an access entry, an indexed project,
  or a manifest of any producer on the disk) is changed by its owner or an
  administrator only (`403 permission_denied`): in a directory that holds the
  other producer's manifest the new one is the second manifest of the same
  project, with its key. A task is changed by the project's owner or an
  administrator (`404` for a hidden project, `403 permission_denied` for one
  seen but not owned) in one manifest: the one of `producer`, else the
  project's only one; a project of both manifests needs `producer` (`400
  producer_required`), and a producer without a manifest in the project is
  `400 other_producer` (both with `details.option` `producer`). Its command is
  in the producer's catalog (`400 unknown_command`), its options are checked
  without the network (`400` with the producer's text and `details.option`),
  and an option that is a file path is `403`. Removing a task keeps its files
  in the store. A producer that changes no projects answers `422 unsupported`
  (`no_project_actions`): IMGWTools until v0.5.
- `archiwista project-download PROJEKT [ZADANIE ...]`, `project-repin PROJEKT
  ZADANIE`, `project-check PROJEKT [ZADANIE ...]` and `project-verify PROJEKT
  [ZADANIE ...]`, each with `--producer PRODUCENT` / `POST
  /projects/{project}/jobs` (`{"kind": "download"}`, `"repin"`, `"check"` or
  `"verify"`, optionally `"tasks": ["…"]`: every task when left out, exactly
  one for a repin, and `"producer"`; v0.3, ADR-040) start a job of the tasks of
  one manifest of the project (section 9), named by `producer` as for a task
  (`400 producer_required`, `400 other_producer`); the job's `params` keep a
  named `producer`. A download and a repin write the store and the manifest
  through the producer, so they need the project's owner or an administrator
  and `store_writer` (or the setting `store_write_for_all`); a check and a
  verification need only to see the project.
- `archiwista status` / `GET /health`: versions, sources, the index and every
  store: `status` (`unknown` not scanned yet, `available`, `unavailable`),
  counters, `last_scan` with the actor, `running_job` with its progress,
  `stale`.

Address a slot and a version by the relative path from the results (`slot`,
`version.path`, `current`), never by a file system path. There is no need to
read the disk or parse sidecars: the API returns everything from the index.

**Freshness.** Every answer from the index has `stale` and `stale_stores`. When
a store is unavailable (for example a disconnected SMB share), lists and cards
still answer `200` from the index as of `indexed_at`, and `stale` is `true`: an
agent should tell the user so, not treat the result as the current state of the
disk.

**Offline mode.** The setting `offline` (`GET /settings`) turns off everything
that needs the network; reading the index, cards and local scans still work,
and a job of unit outlines gets `409 conflict` (`offline_mode`).

**Area and local state.** `POST /areas` keeps an area: a GeoJSON `Polygon` or
`MultiPolygon` in WGS84 as `application/json` (`{"geometry": {…}, "name":
"…"}`), or a GeoJSON, GeoPackage or ZIP with one Shapefile as the raw body (for
example `Content-Type: application/octet-stream`; `?name=` and, for a file with
several layers, `?layer=`). The answer `201` has an `id` (the same geometry
always gets the same one), the area in km² (`area_km2`, `area_crs`) and the
countries. The `id` is the parameter `area_id` of `/slots` (`archiwista search
--area-id`) and of `GET /local-coverage?area_id=…&product=…&store=…`: how much of
the area the current versions of the product in the store cover: `results` with
the country, `percent` (rounded down) and `label` ("lokalnie 83% obszaru").
Before counting, the server reads the area's slots from the store (at most 500,
up to 10 s); otherwise it answers from the index and gives the reason in
`stale_reason`.

```sh
AREA="$(curl -sf -b "$JAR" -H "$H" -H 'Content-Type: application/json' \
  -d '{"geometry": {"type": "Polygon", "coordinates": [[[19.9, 50.0],
       [20.0, 50.0], [20.0, 50.05], [19.9, 50.05], [19.9, 50.0]]]}}' \
  "$BASE/areas" | jq -r .id)"
curl -sf -b "$JAR" -H "$H" "$BASE/local-coverage?area_id=$AREA&product=nmt&store=zespol"
archiwista search --area-id="$AREA" --product=nmt --json
```

**Stations and the coverage of their series** (the IMGWTools source, plans I6 and I8).
`GET /stations` pages the stations of the station catalogs of IMGW-PIB and ČHMÚ along
rivers (`sort=river`, the default: by the hydrographic code, so a tributary follows
its river, then the provider's order on the river, then the name) or by name
(`sort=name`). `q` finds a station whose name or river contains the text (case
ignored; no character is a wildcard) or whose code begins with it; a cursor belongs
to its `q` and `sort`. Filters: `store`, `provider`, `kind`, `active`, `river_code` with
`river_scope` (`exact`, or `tributaries`: every code that begins with it),
`dataset` (a dataset key such as `pl.imgw.hydro_daily`), `variable`, `coverage`
(`Q:continuous`, `H:gaps`; states of one variable are alternatives) and
`min_complete_years` (`Q:30`), all three repeatable and the last two needing
`dataset`, `years` (`1951-2025`, the range R of the labels), `year_type`,
`location` (`any`, `with`, `none`), `limit` and `cursor`; an area is `area_id` or
`bbox` with `bbox_crs`, and it takes the stations on its boundary too, those closer
to it than their location uncertainty (`location.on_boundary`; `boundary=false`
leaves them out). Each item has its `location` and `series[]`: per dataset the
series version, the station's `file` with its `sha256`, the `license`, the
`attribution` to quote with the data, and `coverage` with an entry per variable
(`state`, the `label` in the request's language and the structure behind it); a
station has no single label. `counts` counts the whole result: `located`,
`boundary`, `unlocated` (no position: after the attribute and coverage filters,
never placed in an area; list them with `location=none`) and `hidden` (stations a
coverage filter hid). `GET /stations/{code}` is a station's card, `GET
/stations/{code}/coverage` its variables year by year (`variable` repeatable; each
year's `cell` is `full`, `fraction`, `none` or `unknown`, and an unknown year is
never a gap) and `GET /map/stations?bbox=…` the located stations of a view, with
each variable's state and label when `dataset` is given, or a grid above `limit`. A
code that several stations share answers `400` with `details.reason`
`ambiguous_station` and the stations in `details.stations`: ask again with `store`
and `provider`. Without IMGWTools every station route answers `503
missing_dependency` (`source_unavailable`) with the fix in `hint`. `GET
/stations/datasets` names the datasets with station series (`archiwista stations
datasets`): each one's key, the producer's name of its segment, provider, family,
unit, the year type of its labels, R by default (`years`), the label of its current
series version and its `variables` (the distinct keys of its stations' series); use a
key as `dataset` and a variable as `variable` of the other routes. `meteo_kind`
(repeatable: `synoptic`, `climate`, `precipitation`) keeps the meteo stations of
those kinds, the counts too. Without `year_type` the routes and `archiwista stations`
number the years as `year_types` of `GET /settings` remembers for the data's family
(hydro hydrological and meteo calendar by default; a list of both families, without
`dataset`, `kind` or `meteo_kind`, as hydro); a given `year_type` wins and changes
nothing, and half-year characteristics stay hydrological. `PUT /settings/year-types`
with `{"hydro": …, "meteo": …}` changes the choice (an administrator until each
person's preferences hold it; the action log keeps a change as `settings.update`).
`GET /stations/timeline` (`archiwista stations timeline`) is the Timeline
of a page: the filters, order and cursor of `GET /stations` with `dataset`
required, each item a station with its `series` exactly as `GET
/stations/{code}/coverage` gives it for the same `variable`, `years` and
`year_type`; `variable` keeps the stations with a value of each variable and only
their rows. Read a long list page by page; the years of a page come from the
index in one read. `GET /stations/{code}/series` (`archiwista stations series`) is
the chart of one or two variables (`variable`, once or twice) of a station's
current series, for display only: `dataset` names the series (by default the one
with every variable), `from` and `to` the range (by default the variables' known
span, every day their labels count) and `max_points` (≤ 2,000) the most points a
variable gets: up to that many units each point is a unit's value, beyond it the
least, mean and greatest value of `interval` units (`null` without a value, never
interpolated). `gaps` are the gaps each variable's label counts in `year_type`
(the card's, by default the remembered one; named in the answer) cut at the
range's ends: over the default range their units are the label's known units
without a value and its longest gap is one of them. `markers` are the accumulated
sums and the extremes IMGW published with their dates.
`version` must be the current one in the index (`409` otherwise; read the card
again); half-year characteristics are not drawn as a line (`400`, reason
`half_year_chart`). `GET /stations/compare` (`archiwista stations compare`) is one
variable of 2 to 5 stations' series of one `dataset` over one range: `station`
repeated, each `<store>/<provider>/<code>` in the order of the panels; `from` and
`to` by default the variable's known spans at the stations together. Every
station's `chart` is its own chart (`GET /stations/{code}/series`) over that range,
with the one `interval` of the answer, and its `coverage` the variable's label and
facts as on its card in `year_type`; a station without the series or the variable
keeps its place with `null` for both. No station with the variable is `400`
(reason `unknown_variable`), none with a series of the dataset `404`.

```sh
curl -sf -b "$JAR" -H "$H" "$BASE/stations/datasets"
curl -sf -b "$JAR" -H "$H" \
  "$BASE/stations?area_id=$AREA&dataset=pl.imgw.hydro_daily&coverage=Q:continuous&min_complete_years=Q:30"
curl -sf -b "$JAR" -H "$H" "$BASE/stations/149190310?store=zespol&provider=IMGW-PIB"
curl -sf -b "$JAR" -H "$H" "$BASE/stations/149190310/coverage?variable=Q&years=1981-1983"
curl -sf -b "$JAR" -H "$H" \
  "$BASE/stations/timeline?dataset=pl.imgw.hydro_daily&river_code=2138&river_scope=tributaries"
archiwista stations list --area-id="$AREA" --dataset=pl.imgw.hydro_daily \
  --coverage=Q:continuous --min-complete-years=Q:30 --json
archiwista stations show 149190310 --store=zespol --provider=IMGW-PIB --json
archiwista stations datasets --json
archiwista stations timeline --dataset=pl.imgw.hydro_daily --variable=Q --json
archiwista stations series 149190310 --variable=Q --from=1981-01-01 --to=1983-12-31 --json
archiwista stations compare --station=zespol/IMGW-PIB/149190310 \
  --station=zespol/IMGW-PIB/149200090 --dataset=pl.imgw.hydro_daily --variable=Q --json
```

## 6. Previews, layers, comparison, own data (v0.2), producers' commands and availability (v0.3), file download (v0.4)

Take a `ref` from the answer of the card of a version, of an own file or of a
snapshot: `version:<store>:<version-path>`, `file:<project>:<file-path>` or
`snapshot:<project>:<label>:<file-path>`. Do not build references from absolute
file system paths. Before it touches the preview cache the resolver checks the
visibility of the project. An invisible project gives `404`, a missing right to
a snapshot `403`.

`GET /stores/{store}/versions/{version}/preview` returns `PreviewInfo`: `state`
(`ready`, `needs_build`, `building`, `unavailable`), `kind`, `reason` (`code`,
a `message` and a `fix` in the language of the request), `styles`,
`default_style` and the addresses
`thumbnail_url`, `tiles_url`, `features_url`, `members_url`. For `needs_build`
call `POST …/preview`: `202` returns a job, `200` means the preview is ready.
Fetch the image with `GET …/preview.png?size=512` (`--style` in the CLI, the
parameter `style` over HTTP). The tiles `…/tiles/{z}/{x}/{y}.png`, the vectors
`…/features?bbox=…&zoom=…` and the ZIP listing `…/members` have the same
session and CSRF header protection, **images too**. Requests for a disconnected
store may use the cache and give the reason when it has nothing.

```sh
archiwista search --project=projekt-01 --json
# REF comes from the field ref of a version card or a file card returned by the API.
archiwista preview "$REF" --build --json
archiwista preview "$REF" --output=<data-dir>/podglad.png
```

`POST /previews/warm` (v0.3, ADR-041) prepares the first look at current
versions ahead: the pane's thumbnail (`size=512`, the default style) and the
map's tiles at the file's smallest zoom go into the preview cache, so the first
request for them does not read a slow store. The optional body narrows it:
`{"store": "…", "product": "…", "segment": "…", "project": "…", "area_id":
"…"}`; no body is every store's current versions. `project` adds the working
files of that project's own data, and makes the job the project's: only those
who see the project see it (another session gets `404`, as for an unknown
project). The job (`preview_warm`) runs at the lowest priority, never evicts a
preview used in the last week, and ends `partial` with `stopped: cache_full`
and the number `skipped` when the cache has no more room; `needs_build` counts
the files whose map waits for a local COG (it builds none). `archiwista
preview-warm --json` runs the same in the foreground:

```sh
archiwista preview-warm --store=zespol --product=nmt --json
```

`GET /local-layers?store=demo&product=nmt&area_id=$AREA&group=year` returns the
years (or `group=campaign`), their keys, the coverage and the addresses of
thumbnails and tiles. Without `area_id` it gives counters, not images. Use the
address `thumbnail_url` of the answer; do not guess the key and the version of
the image:

```sh
archiwista layers --store=demo --product=nmt --area-id="$AREA" --json
LAYER="$(archiwista layers --store=demo --product=nmt \
  --area-id="$AREA" --json | jq -r '.layers[0].key')"
archiwista layers --store=demo --product=nmt --area-id="$AREA" \
  --thumbnail="$LAYER" --output=<data-dir>/rok.png
curl -sf -b "$JAR" -H "$H" "$BASE/local-layers?store=demo&product=nmt&area_id=$AREA&group=year"
archiwista compare "$REF_A" "$REF_B" --json
curl -sf -b "$JAR" -H "$H" -G --data-urlencode "a=$REF_A" \
  --data-urlencode "b=$REF_B" "$BASE/compare"
```

The folder of a project (by default `<project directory>/dane/`; its owner or
an administrator sets another one with `PUT /projects/{project}/data-dir`, an
owner who is no administrator only inside the project's directory: `400
validation_error` with the problem `own_data_dir_outside_project`; it is saved
as its real path, and a folder inside the project's directory that a symbolic
link later leads out of is not read, problem `own_folder_invalid`) is
indexed apart from the store: `GET /projects/{project}/files?q=…&state=changed`
with `limit`/`cursor`, `GET …/files/{file_id}` and `GET …/files/{file_id}/layers`
(the working file and its snapshots in the fan). Images, tiles, features and the
listing of an archive have counterparts of the version routes under
`…/files/{file_id}/preview`, `…/files/{file_id}/snapshots/{label}/preview` and
so on. A file changed since the last scan has to be scanned again instead of
using the old preview. A working file or a snapshot of a data folder that
breaks the rules of its scan now (a symbolic link out of the project put in
its place, a folder in a store) is `409 own_folder_invalid` on every preview
route, even for a thumbnail the cache holds, its card has `preview: null` and
its layers are `unavailable`; the `preview` and `preview_warm` jobs fail such
a file with the code `own_folder_invalid`. The snapshot plan checks
feasibility and size without making it; `POST …/snapshots` needs
`project.write` (the project owner or an admin) and returns a `snapshot` job;
identical content gives the result `unchanged`.

```sh
archiwista files projekt-01 --state=changed --json
archiwista file projekt-01 kanalizacja.gpkg --json
archiwista own-scan --project=projekt-01 --json
archiwista snapshot projekt-01 kanalizacja.gpkg --plan --json
archiwista snapshot projekt-01 kanalizacja.gpkg --note="przed zmianą" --json
curl -sf -b "$JAR" -H "$H" "$BASE/projects/projekt-01/files"
curl -sf -b "$JAR" -H "$H" "$BASE/projects/projekt-01/files/$FILE_ID/snapshot-plan"
curl -sf -b "$JAR" -H "$H" -X POST -H 'Content-Type: application/json' \
  -d '{"note":"przed zmianą"}' "$BASE/projects/projekt-01/files/$FILE_ID/snapshots"
```

`GET /jobs?project=projekt-01` filters the jobs of a project. The details
`/jobs/{job}`, the SSE `/jobs/{job}/events` and the log do not reveal jobs with
data of an invisible project (`404` for a direct address); the list holds every
job of the queue, such a job with `hidden: true` and nothing but its kind,
store, who, state, times and progress counts (v0.4, ADR-047). An ordinary store
scan is shared. The SSE sends `progress`, `notice` and `state`, and a client
resumes after `Last-Event-ID`.

**The producers' commands (v0.3, ADR-034).** `GET /commands` lists the commands
of every producer whose plugin offers them (Kartograf's catalog; `?producer=`
keeps one producer): each with its options (JSON type, whether required, the
allowed values and their meanings, the default, bounds, the `group` of mutually
exclusive options and the `path_role` of a file path), what a run does
(`read_only`, `writes`, `network`, `check`, `store`) and complete example lines;
the summary and the description follow `Accept-Language`. `POST /commands/parse`
reads a pasted line into a call (`command`, `options`, and `run`: the store root
and the flags the line gives beside the options), `POST /commands/validate`
checks a call without the network and `POST /commands/format` writes the
producer's canonical line of a call, which parses back into the same call. A
command that works on a store is checked with the directory of a configured
store (`store`), never with the producer's default root, and an option that is a
file path is refused (`403`, `path_outside_root`). The producer's own refusal is
`400 validation_error` with its text and hint and the option in
`details.option`. Nothing here downloads or writes.

```sh
archiwista commands list --producer=kartograf --json
archiwista commands parse kartograf "kartograf sheet parse --sheet N-34-130-D-d-2-4" --json
archiwista commands validate kartograf "elevation download" --store=demo --json \
  --options='{"product": "nmt", "sheet": "N-34-130-D-d-2-4", "resolution": "1m", "vertical_crs": "EVRF2007"}'
curl -sf -b "$JAR" -H "$H" -X POST -H 'Content-Type: application/json' \
  -d '{"producer": "kartograf", "line": "kartograf sheet parse --sheet N-34-130-D-d-2-4"}' \
  "$BASE/commands/parse"
```

**The availability at the source (v0.3, ADR-035).** `POST /availability` with
`{"area_id": "…", "product": "nmt"}` (`producer` is `kartograf` by default; the
products a producer checks are listed in the `422` that refuses another one) asks
what the source has for a kept area. A report the index keeps that is younger
than seven days answers at once: `200` with `AvailabilityInfo`, the area,
`checked_at` (when the source was asked), `job_id` and `report` (the producer's
report: the parts of the area by country with their land, the combinations of a
year, a variant and a format with their full, partial and missing sheets, the
sheet records and campaigns a download takes and `full_m2`, the parts that
failed, the producer's notices, `ok`). Otherwise, or with `"force": true`, the
answer is `202` with the `availability` job (`Location`); a request that asks
what an active check asks gets that job. When the job succeeded, `GET
/availability?area_id=…&product=…` returns its report; it reads only the index,
never the network, and answers `404` without a report. In offline mode a check
that needs the source is `409 conflict` (`offline_mode`) and nothing is
recorded. `archiwista availability check` runs the job in the foreground and
prints the `AvailabilityInfo` it kept (`--json`); a check that does not succeed
prints its `JobDetail` and exits `11` or `130`.

Every `AvailabilityInfo` also reads the report for a person (SPEC 6.3, 6.4):
`rows`, one per year of each country in the report's order, each with the
`label` of its best variant (`complete`, `complete · 2 campaigns`,
`partial · 58% · 1 partial sheet`, `no data`; Polish with `Accept-Language: pl`),
the same as structure in `coverage` (`kind`, `campaigns`, `full_share`,
`percent` rounded down and at most 99 when partial, `below_one`,
`partial_sheets`, `missing_sheets`), `other_variants` and `variants`, best
first (complete, larger full share, fewer campaigns, finer resolution, the
report's order; the formats of one set are one variant with its
`default_format`, ASC then TIFF, and its size). `store` (a configured store,
else `404`) gives every variant its store badge `local` (`state` `all`, `some`
or `none`, `units` of `of`, `label` `downloaded 5/12`); `horizontal`,
`resolution` and `vertical_crs` fix those dimensions, and a year without such
a variant is `no_data`. The command takes them as `--store`, `--horizontal`,
`--resolution` and `--vertical-crs`, and its text prints a line per year.

```sh
curl -sf -b "$JAR" -H "$H" -X POST -H 'Content-Type: application/json' \
  -d "{\"area_id\": \"$AREA\", \"product\": \"nmt\"}" "$BASE/availability"
archiwista availability check "$AREA" --product=nmt --json
archiwista availability show "$AREA" --product=nmt --store=zespol --json
```

**File download (v0.4, ADR-047).** `GET /stores/{store}/versions/{version}/file`,
`GET /projects/{project}/files/{file_id}/file` and `GET
…/files/{file_id}/snapshots/{label}/file` send the file itself: only a version
the index knows, or an own file or a snapshot of a project the session sees
(else `404`), resolved inside its root (a symbolic link out of it is `403
path_outside_root`). One file of a set (a Shapefile, a MapInfo TAB, or a
snapshot of one) is `?member=<name>`, a name from `members` of the file card or
of the snapshot (another name is `404`); without it the main file. An own file
and a snapshot come only from a data folder that its scan's rules let be read
now: a folder that leads out of the project's directory (a symbolic link put
in its place, say) or lies in a store is `409 own_folder_invalid`, one that is
gone `404 missing_file`, and a data folder other than the one the last scan
read `409 own_file_changed`. A working file changed since its scan is `409
own_file_changed`; one its last scan could not read and a snapshot that is not
valid are `409 file_unreadable`; a file gone from the disk is `404
missing_file`. The answer is an attachment
(`Content-Disposition: attachment` with the file's name, `filename*` for a name
that is not ASCII), the media type of its format or extension (else
`application/octet-stream`), `Cache-Control: private, no-store` and
`X-Content-Type-Options: nosniff`; nothing is shown inline, a PDF neither.
`Range` answers `206` with `Content-Range` (`curl -C -` resumes), and `HEAD`
answers the headers only (`Content-Length`). A person, with their agents,
streams at most two files at once: a third is `429 rate_limited`, reason
`too_many_downloads`, with `Retry-After: 10`. A `GET` without `Range` or from
byte 0 is logged (`file.download` with `size_bytes`). These routes need
`X-Archiwista-CSRF` as every other; only a link of the interface
(`Sec-Fetch-Site: same-origin`, or `none` for an address typed in) passes with
the session cookie alone.

```sh
# VERSION_PATH is version.path of a row of /slots; FILE_ID is file_id of the file list.
curl -sf -b "$JAR" -H "$H" --output-dir <data-dir> -OJ \
  "$BASE/projects/projekt-01/files/$FILE_ID/file?member=dzialki.dbf"
curl -sf -b "$JAR" -H "$H" -C - -o <data-dir>/N-34-130-D-d-2-4.asc \
  "$BASE/stores/zespol/versions/$VERSION_PATH/file"
```

## 7. Errors

Every HTTP error is `application/problem+json` (RFC 9457) with a code of the
shared Nogat error registry (ERR §2). For `GET /slots?limit=201`:

```json
{
  "type": "https://github.com/Daldek/Nogat/blob/main/standards/ERROR_REGISTRY.md#validation_error",
  "title": "Invalid input",
  "status": 400,
  "detail": "Invalid request data: query.limit.",
  "instance": "/api/v1/slots",
  "code": "validation_error",
  "details": {"reason": "invalid_request"},
  "errors": [{"pointer": "/query/limit", "type": "less_than_equal",
              "message": "Input should be less than or equal to 200"}]
}
```

Members: `type` is the page of the registry and the anchor of the code; `title`
is the title of the code; `status` is the HTTP status of the code; `detail` and
`hint` (one line telling how to fix it, when a fix is known) say what happened
and what to do; `instance` is the path of the request; `details` holds the
project's own cause in `reason` and the context (below); `errors[]` lists
invalid values with a JSON Pointer.

The texts follow the request header `Accept-Language`: `title`, `detail`,
`hint`, the texts inside `details` (the `message` and `fix` of
`preview_reason`, the `message` of `problems[]`) and the `message` of the
`errors[]` that Archiwista's own validators make are English, and Polish when
Polish has the highest quality in the header; any other language, a malformed
header and no header give English (the `message` that pydantic makes itself
is English always). Every JSON answer under `/api/v1`, a problem and an event
stream have `Content-Language` (`en` or `pl`) and `Vary: Accept-Language`;
images, `/api/v1/openapi.json` (English always) and the files of the interface
have neither. What is written when it happens, and not when it is read, stays
Polish whatever the request says: the `detail` of a store that is not
`available`, and the `message` of the `notice` events of a job (section 9).

Base decisions on `status`, `code` and `details.reason`, never on the text of
`detail`.

| Status | `code` | `details.reason` and what to do |
|---|---|---|
| 400 | `validation_error` | `invalid_request`: invalid parameters or body, see `errors` (`pointer`, `type`, `message`); `invalid_settings`: `details.problems` (`code`, `field`, `message`, and `reason` and `hint` when the producer refuses the directory: `no_marker`, `unsupported_marker`, `foreign_store` or `not_a_store` for Kartograf); `invalid_ref`: a malformed reference; `area_too_large`: an area file over 50 MB or an archive over 200 MB unpacked; `area_too_complex`: more than 100 000 vertices; `request_too_large`: the body is over the limit (4 KiB for the token exchange, 16 KiB for a sign-in, 1 MiB for the rest); `kartograf_error`: the producer refused a command line or a call (`/commands/…`), its own text and hint, the option in `details.option`; `unknown_command`, `store_required`, `store_without_producer`: a command outside the producer's catalog, a command on a store without `store`, a store without a directory of the producer (`details.option`); `producer_required`, `other_producer`: a change or a job of a project with the manifests of both producers that names no `producer`, or a `producer` without a manifest in the project (`details.option` `producer`); `ambiguous_station`: a station code that several stations share, named in `details.stations` (`store`, `provider`); `password_policy`: a new password breaks a rule, `details.rule` `too_short` (under 12 characters after NFKC), `too_long` (over 1,024), `account_name` (the account's id or name) or `common` (a common password); `password_mismatch` (`users password` only): the two typed passwords differ; no reason: an unknown store, area or cursor, a coverage filter without `dataset`, a reversed range of years |
| 401 | `unauthorized` | `session_required`: no, expired or unknown session; a wrong, used or expired token → a new token; `login_failed` (team mode): the account and password do not sign in, one answer for every cause, or the reverse proxy names no enabled account (`POST /session/proxy`); `password_expired`: a correct temporary password past its end, an administrator gives a new one |
| 403 | `forbidden` | `csrf_rejected`: no or wrong `X-Archiwista-CSRF` in any `/api` request, or a foreign `Origin`; `invalid_host`: a `Host` other than `127.0.0.1:<port>`/`localhost:<port>` (team mode: other than the host of `origin`); `tls_required`: team mode, a request not over HTTPS; `proxy_required`: team mode behind a reverse proxy, a request that did not come through it; `password_change_required`: the session's temporary password must be changed first (`PUT /session/password`); `wrong_password`: the current password given to `PUT /session/password` is wrong; `permission_denied`: the actor has no right (for example a settings change without the role `admin`); `path_outside_root`: the path leaves the store, or an option of a command is a file path (`details.option`) |
| 404 | `not_found` | an unknown resource, or a project invisible to the actor; `missing_file`: the file of a download (`…/file`) is gone from the disk, the next scan updates the index |
| 405 | `method_not_allowed` | another method; the allowed ones are in the header `Allow` |
| 409 | `conflict` | no reason: a job that writes this store's index runs already (`details.job`: `id`, `kind`, `state`), follow it instead of retrying; `offline_mode`: the operation needs the network and offline mode is on; `snapshot_blocked` (`details.blocked_by`) or `own_file_changed`: the plan blocks the snapshot or the file changed since its scan, refresh the folder and read the plan; `preview_not_ready`: the preview needs its build first (`details.build_required`, or `details.job`/`details.building` while it builds); `file_unreadable`: a download (`…/file`) of a working file its last scan could not read, of a snapshot that is not valid, or from a data folder that cannot be read; `own_folder_invalid`: a download or a preview (its description, images, tiles, features, members or build) of an own file or a snapshot whose data folder breaks the rules of its scan now (it leads out of the project's directory, lies in a store), an administrator or the project's owner fixes the folder; `last_admin` (team mode): the change would leave no enabled account with the role `admin`, give another account the role first; `local_mode`: signing in and changing a password exist in team mode only; `proxy_session`: a session of the reverse proxy changes no password |
| 422 | `unsupported` | `preview_unavailable`: the file has no preview of the kind asked for (`details.preview_reason`: `code`, `message`, `fix`); `no_commands`: the producer offers no commands; `no_availability`: the producer checks no availability of the product (`details.allowed`: the products it checks) |
| 422 | `calculation_error` | `preview_timeout`: a render process ran past its time limit |
| 429 | `rate_limited` | `preview_busy`: the render pool is full; `login_blocked`: too many failed sign-ins of the account or the address; `scan_running`: the person's scan of a data folder waits or runs; `scan_too_soon`: the project's folder was asked to be scanned less than a minute ago; `too_many_downloads`: the person streams two file downloads (`…/file`) already; wait for `Retry-After` (also `details.retry_after_s`) |
| 500 | `data_error` | `area_unreadable`: an area file cannot be read (for a file with several layers `details.layers`: choose one with `?layer=`); `kartograf_error`, `imgwtools_error`, `producer_error`: the producer rejected the call, `details.kartograf`/`details.imgwtools` have `exception` and the unchanged `message` |
| 500 | `internal_error` | a defect of Archiwista: details in the server's log |
| 503 | `missing_dependency` | `source_unavailable`: the producer plugin is missing; `source_incompatible`: it has an unsupported version or schema; `details.source` (`id`, `state`, `package_version`, `supported_versions`, `requirement`), the fix is in `hint` and at the end of `detail` |
| 503 | `store_unavailable` | `store_unreadable`: the store cannot be read and the index has no answer |

The command line gives the same information as the error document
`archiwista-error/1` on the last line of standard error (nothing goes to
standard output), for example for `archiwista search --limit=201 --json`:

```json
{"schema":"archiwista-error/1","code":"validation_error","title":"Invalid input","message":"Invalid request data: query.limit.","details":{"reason":"invalid_request","errors":[{"pointer":"/query/limit","type":"less_than_equal","message":"Input should be less than or equal to 200"}]},"exit_code":2}
```

`exit_code` is the registry's exit code of `code` (`null` for the codes that
exist only in REST: `unauthorized`, `method_not_allowed`, `rate_limited`; the
command then exits `1`); `message` and `hint` are English, as the document is
machine output, and the line before it, for a person, says the same in Polish;
`command` is the `<group> <verb>` of the command when it has that shape. The
schema is `schemas/nogat/error-1.schema.json`.

## 8. Recommended workflow of an agent

1. **Orientation:** `archiwista status --json` (or `GET /health`): are there
   stores, are they `available`, is the producer plugin `available`, does a
   scan run (`running_job`).
2. **Search:** `search` with the narrowest possible filters (`--product`,
   `--unit`, `--years`, `--bbox`), `--limit=200` and a loop over `next_cursor`;
   do not fetch the whole catalog when a filter is enough.
3. **Details:** the card of a file (`entry`) for the chosen slots; `version`
   only when all metadata or the sidecar are needed.
4. **Freshness:** check `stale`; when it is `true`, give the user `indexed_at`
   from `stale_stores` instead of claiming that the file is on the disk.
5. **Refresh (on request only):** `POST /stores/{store}/scan` with CSRF → `202`
   with a job (an administrator's from v0.4: `403 permission_denied`
   otherwise); follow the progress over SSE or `GET /health` (`running_job`).
   On `409 conflict` wait for the running job instead of retrying.
6. **Errors:** pass `503 missing_dependency` (`source_unavailable` or
   `source_incompatible`) to the user with the fix from `hint`, and do not
   retry in a loop; `401` → a new token from the user (`archiwista token`; on a
   team server `archiwista token --user ID` or the person's `POST
   /session/tokens`); `429 login_blocked`, `scan_running` or `scan_too_soon`
   → wait for `Retry-After`.
7. **Paths:** to work with a file use `paths.local` from the card; do not build
   paths yourself.

## 9. Background jobs and SSE

Long operations return `202 Accepted` with a job (`JobDetail`) and the header
`Location: /api/v1/jobs/{id}`. All need `X-Archiwista-CSRF`.

| Request | Body | Notes |
|---|---|---|
| `POST /stores/{store}/scan` | optionally `{"mode": "incremental"}` (default) or `"full"`, optionally `"segment"` | scan of a store into the index, an administrator's (v0.4, `store.scan`); a `segment` is scanned by the data source that owns it, and a source that reads only its whole directory (IMGWTools: a segment is a dataset) ends the job as `unsupported` |
| `POST /stores/{store}/footprints` | none | unit outlines (TERYT, KU) from the network, an administrator's (v0.4); offline → `409 conflict` (`offline_mode`) |
| `POST /stores/{store}/link-check` | `{"slot": "…"}` | confirmation of the target of a slot's link, an administrator's (v0.4); an unknown slot → `404` |
| `POST /projects/{project}/scan` | none | scan of the project's folder, open to those who see the project; a waiting scan of the folder is joined; otherwise (v0.4) a person, with their agents, has one such scan waiting or running (`429 rate_limited`, `scan_running`) and a folder is asked for once a minute (`scan_too_soon`), with `Retry-After`; the computer's owner is not limited |
| `POST /projects/{project}/files/{file_id}/snapshots` | `{"note":"…"}` or none | a snapshot, needs `project.write` |
| `POST /projects/{project}/jobs` | `{"kind": "download"}`, `"repin"` (with `"tasks": ["…"]`, exactly one), `"check"` or `"verify"`; optionally `"tasks"` (every task when left out) and `"producer"` (the manifest whose tasks run, needed for a project with the manifests of both producers) | a job of the tasks of a project's manifest (v0.3, ADR-040): `project_download` downloads and pins the tasks not downloaded yet and restores missing pinned versions in the configured store the manifest names, `project_repin` pins one task anew to the source's newer versions, `project_check` compares the pins with the source without effects, `project_verify` checks the pinned files in the store (no network); the job has no `store`, its `params` are `project` and `tasks`, with `producer` when the request named it. A download and a repin need the project's owner or an administrator and `store_writer` (`403`); a hidden project is `404`; refused before a job: no `producer` for a project of both manifests (`400`, `producer_required`) or one without a manifest in it (`400`, `other_producer`), a manifest naming no configured store (`409`, `unknown_store`), a producer without project jobs (`422`, `no_project_actions`), a second job of the project (`409 conflict`, `details.job`), offline mode for all but `verify` (`409 offline_mode`). A lock of the manifest that stays fails the job (`conflict`, `project_locked`, `details.lock`) |
| `POST …/preview` | none | build of the preview of a file or a version (answer `200` or a job `202`) |
| `POST /previews/warm` | none, or any of `{"store": "…", "product": "…", "segment": "…", "project": "…", "area_id": "…"}` | the first look at current versions prepared in the preview cache (v0.3, ADR-041): the job `preview_warm` has no `store`, its `params` are the filters (and `since`, set only by the scheduler's warm-up after a scan); any session may ask; a store that is not configured, a project the session does not see and an unknown area → `404` before a job; a request of the filters of a waiting warm-up returns that job |
| `POST /availability` | `{"area_id": "…", "product": "…"}`, optionally `"producer"`, `"force"`, and `"store"`, `"horizontal"`, `"resolution"`, `"vertical_crs"` for the rows of a `200` | what the source has for a kept area (v0.3): a report younger than seven days answers `200` without a job (unless `force`), else the `availability` job `202`; offline → `409 conflict` (`offline_mode`); a store that is not configured → `404` before a job |
| `POST /jobs` | `{"kind": "check", "producer": "…", "store": "…", "calls": [{"command": "…", "options": {…}}, …]}` (1 to 1000 calls, in their order; one for one line); for a run `"kind": "download"`, optionally `"plan_job": "…"` (a `check` job of the same store, producer and calls in the same order) | a job of calls of commands of the producer's catalog that work on a store and have a check (v0.3): all the lines of a report's row, or of a pasted list, in one job (ADR-044). `check` plans a run of each call in the store's directory of the producer without its effects, one after the other, and keeps a plan of each; a call the producer refuses, or none of whose positions could be checked, keeps none and the job ends `partial` (it fails only when no call was planned, with the first call's error); `download` runs the calls there (with `plan_job` each call only its plan's positions to download, one whose source changed since a failed item, `stale_plan`; a call without a kept plan or with nothing to download is skipped), the next call running after one that failed; both over the network. `result.calls` says what became of each call (`status`, `line`, `error`; a download's `reason` of a skipped one), `files[]` and `items[]` of a download carry the `call`. Refused before a job exists: a download by a session without `store_writer` (and without the setting `store_write_for_all`) `403` (`permission_denied`; an agent has the roles of the person who issued its token), a store that is not configured `404`, a command outside the catalog `400` (`unknown_command`), a store without a directory of the producer `400` (`store_without_producer`), a command on no store or without a check `422` (`no_store`, `no_check`), an option that is a file path `403` (`path_outside_root`), the producer's refusal of the options `400` (its text, `details.option`), each refusal of one call naming its place in `calls` (`details.call`, from 0), a `plan_job` the session does not see or that kept no plan `404`, one of another store, producer or calls `409` (`plan_mismatch`, `details.job`), `plan_job` with `check` `400`, a missing plugin `503`, offline `409` (`offline_mode`); the job keeps the options as the producer read them. A download that shares a call (store, producer, command, options) with an active download starts with the warning notice `overlapping_job` |

An unknown store gives `404 not_found`, a wrong body `400 validation_error`.
When a job that writes the store's index (a scan or outlines) runs already, the
answer is `409 conflict` with `details.job` (`id`, `kind`, `state`): follow that
job instead of creating another.

A job (`GET /jobs/{id}`) has the fields `id`, `kind` (`scan`, `footprints`,
`link_check`, `preview`, `own_scan`, `snapshot`, `availability`, `check`, `download`,
`project_download`, `project_repin`, `project_check`, `project_verify`, `preview_warm`), `state` (`queued`, `running`,
`succeeded`, `partial` (part of its units failed: `result` names them), `failed`, `interrupted`, `cancelled`), `actor`, `actor_kind`,
`session`, `store`, `params`, `created_at`, `started_at`, `finished_at`,
`progress`, `result`, `error` and `hidden` (v0.4: a job only of projects the
session does not see, listed with empty `params`, `null` `session`, `result` and
`error`, and `progress` with `current` and `total` only). The list: `GET
/jobs?kind=&store=&state=&project=` with `limit` (1–200) and `cursor`, newest
first. Jobs with project data check the visibility of the project in a single
card and in the SSE stream too.

**The shared queue (v0.4, ADR-047).** A `download` with `plan_job` claims the
positions to download of its plans when it starts; a position another active
download of the store claimed first is left to that job: `result.taken` lists it
(`path`, `unit`, `job`, `actor`), a notice `taken_by_job` names each such job and
its person, a call all of whose positions are taken is skipped (`reason`
`taken`), and the job ends `partial`, so `POST /jobs/{id}/retry` fetches what
the other job failed. A `download` without `plan_job` of a call (store, producer,
command, options) that a running download runs stays `queued` with a notice
`waiting_for_job` naming that job, and runs when it ends, finding the files in
the store. A person (with their agents; the scheduler is no person) runs at most
`network_jobs_per_person` network jobs at once (`GET`/`PUT /settings`, 2 by
default); further ones stay `queued`, none is refused, and a free place goes to
the oldest waiting job of the person with the fewest running ones.

The plans of a `check` job that succeeded or ended `partial` are `GET
/jobs/{id}/plan` (`ActionPlanInfo`, from the index, no network): the store, the
producer, the root, `checked_at` (of the oldest plan), `ok` (every call planned
and every position checked), the totals of all the plans (`counts` of each
status, `positions`, `todo`, `size_bytes` (`null` when the producer tells no
size, never 0) with `size_complete`), and `calls`, the plan of each call planned
in the order of the job's calls: `call` (its place, from 0), `command`,
`options`, the producer's command line of its run (`line`, with the store's
root), `schema`, `checked_at`, `ok`, `counts`, `todo`, `size_bytes`,
`size_complete`, `notices` and `entries`: `path` below the store root, `unit`,
`status` (`current`, `newer`, `missing`, `unverifiable`, `check_failed`),
`local_label`, `available_label`, `size_bytes`, `error`, `conflict`. A call
whose check failed has no plan; the job's `result.calls` says why. A job the
session does not see, one that is no `check`, one still running and one that
failed are `404`.

A job is controlled by (v0.3; ADR-038):

- `POST /jobs/{id}/cancel` (no body): a job that waits ends `cancelled` at once,
  without a worker; a running one is interrupted and ends `cancelled` once its
  worker has stopped, within 30 s. The answer is `202` with the job as it is
  then (often still `running`): follow its events to the end. A job another
  process runs (`archiwista jobs start` at a terminal, or a server's job
  cancelled with `archiwista jobs cancel`) is stopped by that process within a
  second. Only whoever started the job (`actor`; an agent acts as the person
  who issued its token) or an administrator may: `403 permission_denied`; a
  job that has ended is `409 conflict`, reason `job_finished`.
- `POST /jobs/{id}/retry` (no body): a job that ended `partial`, `failed`,
  `interrupted` or `cancelled` starts again as a new job of the session with its
  kind, store and `params` (`202`, `Location` of the new job; the old job stays
  as it ended). A download fetches only what the store still lacks. One that
  succeeded is `409`, reason `job_succeeded`; one that waits or runs
  `job_active`; a download needs `store_writer` again (`403`), a snapshot the
  project's owner, a project's download or repin both; the new job is refused as
  any job of its kind (`409` for a store whose index another job writes, offline
  mode).
- `GET /jobs/{id}/log`: the end of the job's log, its worker's standard error in
  English (`JobLog`: `job`, `size_bytes` of the whole log, `truncated` when only
  its last MiB is given, `text`). A job that never started a worker, or whose
  log went with the old logs (90 days, 1 GB), is `404`; a `preview` job that
  also builds files of projects the session does not see is `403`.

A job the session does not see is `404` for all three.

Events flow as SSE from `GET /jobs/{id}/events` (`text/event-stream`). Every
frame has `id: <sequence number>`, `event: progress|notice|state` and
`data: <JSON>`:

- `progress`: `current`, `total`; a scan adds `segment` and `entries`, outlines
  `written` and `failed`;
- `notice`: `level`, `code`, `message` (Polish, as written when the job ran);
- `state`: `state`; the last one carries `result` (success; its texts are
  Polish) or `error` (in the language of the request, below).

The stream ends after the final state; for a finished job without new events
the answer is `204`. After 15 s of silence the server sends the comment
`: keepalive`, and a queued job may wait longer, so the client should have no
read timeout (for example `httpx` with `timeout=None`). After a broken
connection resume with the header `Last-Event-ID` equal to the last received
`id`.

The stream, like every `/api` request, needs the header `X-Archiwista-CSRF`.
The browser's `EventSource` sends no headers of its own, so it does not fit
here: read the stream with an ordinary HTTP client that reads the body as it
arrives: `curl -N`, `httpx.stream(…)`, and `fetch` with `response.body` in the
browser (as the Archiwista interface does).

```sh
JOB="$(curl -sf -b "$JAR" -H "$H" -X POST \
  "$BASE/stores/zespol/scan" | jq -r .id)"
curl -sfN -b "$JAR" -H "$H" "$BASE/jobs/$JOB/events"
curl -sf -b "$JAR" -H "$H" "$BASE/jobs/$JOB" | jq '{state, error}'
```

The `error` of a job that did not succeed (`failed`, `interrupted`, `cancelled`) is
described as a problem is (section 7): `code` is a code of the error registry,
`detail` says what happened and `hint` tells how to fix it when a fix is known
(both in the language of the request, also in the final `state` event: the job
keeps the key and the values of each text and renders them when it is read), and
`details` holds the job's own cause as `reason` and the context, whose texts are
Polish, as is the `message` of a `notice` and as is the `detail` of a job
recorded before the texts followed the request. Base decisions on `code` and
`details.reason`, never on the text of `detail`:

| `code` | `details.reason` | What it means |
|---|---|---|
| `store_unavailable` | `store_unreadable` | the store cannot be read now (an unmounted share); the index stays as it was, try again later |
| `store_unavailable` | `no_marker`, `unsupported_marker`, `foreign_store`, `not_a_store` | the producer refuses the directory (Kartograf: no `kartograf-store.json` beside a layout, a marker of another schema or not JSON, the root of an IMGW store, the parent of a store); `hint` gives the command, for `no_marker` `kartograf store init --root <path>`, which marks the store once; the index stays as it was |
| `missing_dependency` | `source_unavailable`, `source_incompatible` | the producer plugin is missing or has an unsupported version: `details.source` and `hint` give the fix |
| `missing_dependency` | `own_reader_failed` | the process that reads own data did not start (for example without the GDAL bindings) |
| `conflict` | `offline_mode` | the job needs the network and offline mode is on |
| `conflict` | `snapshot_blocked` | the plan refuses the snapshot: `details.blocked_by` is `folder_invalid`, `read_only_folder`, `insufficient_space` or `file_missing` |
| `conflict` | `inconsistent_copy`, `target_exists` | a snapshot: the file kept changing while it was copied, or another process published the label first; nothing was published, try again |
| `conflict` | `project_locked` | a job of a project: the lock of its manifest stays (`details.lock`), left by a change that was interrupted while it wrote; remove the directory when no program is changing the project and try again (Archiwista never removes it) |
| `conflict` | `unknown_store` | a project's download or repin: its manifest names no configured store; nothing was written |
| the code of the first failure, e.g. `data_error` | `run_failed` | no unit of a run, or no task of a project's download, succeeded; `details.task` names a project's first failed task |
| `data_error` | `checksum_mismatch`, `integrity_failed` | a snapshot copy differs from its source or fails the SQLite integrity check; nothing was published |
| `data_error` | `kartograf_error` (`<package>_error`) | the producer rejected the call: `details.kartograf` has `exception` and the unchanged `message` |
| `forbidden` | `path_outside_root` | a path leaves the store or the project folder |
| `not_found` | none | the store, slot, project or file is unknown |
| `unsupported` | none | the producer cannot do it (a link check without link support; a scan of one segment of a directory the producer reads whole, as IMGWTools does) |
| `cancelled` | none | cancelled by the person, or the store was removed |
| `cancelled` | `interrupted` | the server stopped or the worker was interrupted; safe to try again |
| `internal_error` | `worker_crashed` | the worker ended without a result: `detail` names the signal or exit status and the job log |
| `internal_error` | `protocol_error` | the worker could not read its job |
| `internal_error` | none | a defect of Archiwista: details are in the job log |

Jobs recorded by 0.2.0 are read with these codes too (their old job code is the
reason). The CLI's job commands are `archiwista jobs start`, `jobs retry`, the
project commands `project-download`, `project-repin`, `project-check` and
`project-verify`, and `preview-warm` (a job in the foreground; they print the
job's `JobDetail` as it ended and exit `0`, `10` for `partial`, `11` or `130`),
and `jobs list`, `jobs show`, `jobs cancel`, `jobs plan` and `jobs log`, which
exit `0`; `jobs cancel` also stops a
job a running server supervises. `archiwista reindex [--store MAGAZYN]` runs a
full scan in the foreground (for the owner at a terminal, not for an agent next
to a running server: both go to the same queue and get a conflict, exit `4`,
when they meet).

## 10. The action log (v0.4, administrators)

The log says who did what, when and from where (A-ADR-047, SPEC 10.2): changes of
accounts, groups, sharing and settings, the jobs people start, cancel or retry, file
downloads, refusals (`403`), the pruning of old entries and the exports of the log
itself (on a team server also sign-ins and sessions). Only an administrator reads it
(`log.read`); anyone else gets `403 permission_denied`, which is logged too. The CLI
acts as the owner of the installation, who is one.

- **Filters** of `GET /log`, `GET /log/export` and both commands (`--actor` …):
  `actor` (an account id, `local`, or `-` before a sign-in), `action` (a name such
  as `job.start`, or a group by its prefix ending with a dot: `session.`),
  `outcome` (`ok`, `denied`, `failed`), `target`, `since` (inclusive) and `until`
  (exclusive), ISO 8601 with a zone; a time without a zone is `400`.
- **A page** (`ActionPage`, newest first): `items` (`ActionEntryModel`: `id`, `at`
  in UTC, `actor`, `actor_kind`, `session`, `client`, `action`, `target`,
  `outcome`, `before`, `after`, `details`), `total` (the entries of all pages of
  the filters) and `next_cursor`, paged as in section 4 (`limit` 1–200, 50 by
  default). Reading is not logged.
- **An export** is logged first (`log.export` with its `filters`, `format` and
  `count`) and holds every entry older than that one, newest first, as an
  attachment: JSON Lines (`format=jsonl`, the default; `application/jsonl`, an
  `ActionEntryModel` per line) or CSV (`format=csv`; UTF-8 with a BOM, CRLF, a
  header of the field names, the objects as JSON text, null as an empty cell). A
  CSV cell that starts with `=`, `+`, `-`, `@`, a tab, CR or LF begins with `'`, so
  a spreadsheet shows it as text: drop that `'` to read the value. `archiwista log
  export` writes the same bytes to standard output, or replaces `--output FILE`
  (mode `0600`).

```sh
curl -sf -b "$JAR" -H "$H" "$BASE/log?action=permission.&since=2026-10-01T00:00:00%2B02:00"
archiwista log list --actor marek.lis --json
archiwista log export --format csv --since 2026-10-01T00:00:00+02:00 --output dziennik.csv
```

## 11. Limits of v0.3

- Local mode only: one person on `127.0.0.1`, no login; accounts and groups
  serve the visibility of projects (A-ADR-029).
- Actions run the commands of Kartograf's catalog; IMGWTools has no actions yet
  (v0.5). An area is a drawn, sheet or file area as in v0.1, not the name of an
  administrative unit (plan A15, Kartograf KB-7).
- The files of an IMGWTools store are indexed (archives, series, station
  catalogs), and its stations and the coverage of their series are read through
  `/stations` and `archiwista stations` (section 5); the stations in the
  interface, the chart data, the comparison of stations and the archive badge
  are v0.5. No chat and no MCP; an external agent uses the API described above.
