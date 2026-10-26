/**
 * JSDoc types of the API's answers and parameters (no code: there is no
 * type checker without a build step, docs/DEVELOPMENT_STANDARDS.md 4.3).
 *
 * The models of steps 8 and 9a follow the OpenAPI document
 * (`/api/v1/openapi.json`, one Pydantic model each in archiwista/api), the
 * jobs (9b) and areas (9c) their route contracts. Timestamps and dates are
 * ISO 8601 strings; `format.js` turns them into `RRRR.MM.DD` for people.
 */

// Session (step 8) -----------------------------------------------------------

/**
 * The current session.
 *
 * @typedef {object} SessionState
 * @property {string} actor - Who acts: the principal's id (`local` for the computer's owner).
 * @property {string} name - The account's display name; the id for the computer's owner.
 * @property {"local_owner"|"user"|"agent"} kind - How: the owner, a signed-in person
 *   (team mode) or an agent for `actor`.
 * @property {string[]} roles - Roles `actor` has now, read again for each request:
 *   `admin` (accounts, settings, every project's data folder), `store_writer`; an
 *   agent has those of `actor`. The owner of a local installation has both.
 * @property {string[]} groups - Groups `actor` belongs to now.
 * @property {boolean} store_write - Whether `actor` may write the stores now (a
 *   `download` job): the role `store_writer` or the setting `store_write_for_all`.
 * @property {string} label - Label of the session, recorded with its jobs and the
 *   action log.
 * @property {"startup"|"token"|"password"|"proxy"} method - How it started.
 * @property {boolean} password_change_required - Signed in with a temporary
 *   password: until `PUT /session/password` it may only read itself and sign out.
 * @property {boolean} team - The server runs in team mode.
 * @property {string} expires_at - End of the session unless used again: each request
 *   extends it by 24 h, in team mode by 8 h and never past 7 days after its start;
 *   an agent's session ends 12 h after its start at the latest.
 */

/**
 * How a session starts on this server (`GET /session/methods`, no session).
 *
 * @typedef {object} SessionMethods
 * @property {"local"|"team"} mode - `local`: one person, one-time tokens;
 *   `team`: people sign in with accounts.
 * @property {boolean} password - Signing in with an account's password.
 * @property {boolean} proxy - This request came from the company's trusted
 *   reverse proxy naming a person: `POST /session/proxy` signs them in.
 */

/**
 * A session just started, with its CSRF token (answered only here).
 *
 * @typedef {SessionState & {csrf_token: string}} NewSession - `csrf_token`: send as
 *   X-Archiwista-CSRF with every /api request, reads included.
 */

/**
 * A one-time token for an agent's session.
 *
 * @typedef {object} OneTimeToken
 * @property {string} token - Value for POST /api/v1/session (single use).
 * @property {string} url - Address that opens a browser session.
 * @property {string} label - Label of the session it opens, recorded with its jobs.
 * @property {string} expires_at - End of validity (5 minutes).
 */

// Problems -------------------------------------------------------------------

/**
 * An error, as `application/problem+json` (RFC 9457) with the registry's
 * members (ERR-4, AGI-6.3); the server answers in Polish for the request
 * header `Accept-Language: pl`, which `api.js` sends.
 *
 * @typedef {object} Problem
 * @property {string} type - The code's entry on the registry page
 *   (`…/ERROR_REGISTRY.md#<code>`); `about:blank` for a problem the page makes.
 * @property {string} title - Polish title of the code.
 * @property {number} status - HTTP status of the code; `0` when the server did
 *   not answer.
 * @property {string} detail - Polish description: what and how to fix.
 * @property {string} [instance] - The request path that failed.
 * @property {string} code - Code of the Nogat error registry: validation_error,
 *   not_found, conflict, forbidden, unauthorized, method_not_allowed, rate_limited,
 *   missing_dependency, store_unavailable, data_error, unsupported,
 *   calculation_error, internal_error…; the page makes `source_unavailable`
 *   problems of its own when the server does not answer.
 * @property {string} [hint] - Polish line telling how to fix it.
 * @property {ProblemDetails} [details] - The reason and the context.
 * @property {Array<{pointer: string, type: string, message: string}>} [errors] -
 *   Invalid request data: the JSON Pointer of each value (`/query/limit`).
 */

/**
 * The project's own cause and the context of a problem (`details`).
 *
 * @typedef {object} ProblemDetails
 * @property {string} [reason] - Finer cause under the code: session_required,
 *   csrf_rejected, invalid_host, permission_denied, path_outside_root,
 *   offline_mode, own_file_changed, snapshot_blocked, preview_not_ready,
 *   preview_unavailable, invalid_ref, invalid_settings, area_too_large,
 *   area_too_complex, area_unreadable, request_too_large, source_unavailable,
 *   source_incompatible, kartograf_error, store_unreadable…; the page adds
 *   network_error, http_error and stream_closed.
 * @property {Array<{code: string, field: string, message: string, reason?: string,
 *   hint?: string}>} [problems] - Invalid settings, field by field (`field` like
 *   `stores[0].kartograf`); `reason` and `hint` when a producer refuses a directory.
 * @property {{id: string, state: string, package_version: string|null,
 *   supported_versions: string|null, requirement: string}} [source] - An unavailable
 *   producer plugin and the pip requirement fixing it.
 * @property {{id: string, kind: string, state: string}} [job] - The running job of a
 *   `409 conflict`, or building a preview that is not ready.
 * @property {boolean} [building] - A preview is being built (its job is not visible).
 * @property {boolean} [build_required] - A preview needs its build first.
 * @property {{code: string, message: string, fix: string, detail: string|null}}
 *   [preview_reason] - Why a file has no preview of the kind asked for.
 * @property {string} [blocked_by] - Why a snapshot cannot be made now.
 * @property {string[]} [layers] - The layers of an area file to choose from.
 * @property {{exception: string, message: string}} [kartograf] - The producer's own
 *   error (`imgwtools` and other producers likewise).
 */

// Index state (9a: /health, /sources, /stores) -------------------------------

/**
 * Versions, sources, the index and every configured store's state.
 *
 * @typedef {object} Health
 * @property {string} archiwista - Archiwista's version.
 * @property {SourceInfo[]} sources - Producer plugins with their library versions.
 * @property {IndexInfo} index
 * @property {StoreItem[]} stores - Configured stores: availability, last scan, running
 *   job.
 * @property {PreviewsState|null} [previews] - Preview cache and render processes of the
 *   server (v0.2).
 * @property {OwnDataState|null} [own_data] - The scans of the projects' own data (v0.2).
 */

/**
 * The scans of every project's own data (`own_scan` of all projects).
 *
 * @typedef {object} OwnDataState
 * @property {string|null} finished_at - End of the last one, whatever its outcome.
 * @property {boolean} busy - Whether such a scan waits or runs.
 */

/**
 * The local index file.
 *
 * @typedef {object} IndexInfo
 * @property {number} schema_version
 * @property {string|null} created_at
 * @property {number} size_bytes
 */

/**
 * @typedef {"available"|"not_installed"|"incompatible"|"error"} SourceStatus
 */

/**
 * A producer plugin: state, versions, schemas and how to fix it (SPEC 5.8).
 *
 * @typedef {object} SourceInfo
 * @property {string} producer
 * @property {SourceStatus} status - `available`, `not_installed`, `incompatible` or
 *   `error`.
 * @property {string|null} package_version - Installed producer library.
 * @property {string|null} supported_versions - Supported range (PEP 440).
 * @property {string[]} schemas - Schemas the plugin reads.
 * @property {string|null} detail
 * @property {string} message - Polish description of the state.
 * @property {string|null} fix - Polish fix; null when available.
 */

/**
 * The directory a producer uses for a store when a call names none (`GET /sources`).
 * Archiwista never uses it; the wizard offers it when it is a store.
 *
 * @typedef {object} DefaultRoot
 * @property {string} path - The directory; it may not exist.
 * @property {"default"|"env"|"dotenv"|"file"} source - Where the producer's settings found it:
 *   `default` (under the data directory), `env` (an environment variable), `dotenv` (the
 *   same variable in a `.env` file) or `file` (`nogat.toml`).
 * @property {string|null} name - The variable or the table that gave it.
 * @property {boolean} exists - Whether it is a directory.
 * @property {boolean} marked - Whether it holds the producer's store marker.
 * @property {string} message - Description of the root, in the language of the request.
 */

/**
 * A producer plugin of `GET /sources`: its state, its default store root and the
 * products whose availability at the source it checks (`POST /availability`), in
 * its order; none when the plugin is not available or checks none.
 *
 * @typedef {SourceInfo & {default_root: DefaultRoot|null, availability: string[]}}
 *   SourceListItem
 */

/**
 * Every registered producer plugin, ordered by producer.
 *
 * @typedef {object} SourceList
 * @property {SourceListItem[]} items
 */

/**
 * @typedef {"local"|"share"} StoreKind
 */

/**
 * @typedef {"unknown"|"available"|"unavailable"} StoreStatus
 */

/**
 * A configured store with its index state.
 *
 * @typedef {object} StoreItem
 * @property {string} store - Store id.
 * @property {string} name
 * @property {StoreKind} kind - `local` disk or network `share`.
 * @property {string[]} producers - Producers with a directory in it.
 * @property {StoreState} state
 */

/**
 * Configured stores in settings order.
 *
 * @typedef {object} StoreList
 * @property {StoreItem[]} items
 */

/**
 * A store's index state: availability, counts, last scan, running job.
 *
 * @typedef {object} StoreState
 * @property {StoreStatus} status - `unknown` (not scanned yet), `available` or
 *   `unavailable`.
 * @property {string|null} status_at
 * @property {string|null} detail - Why the store is unavailable.
 * @property {string|null} indexed_at - End of the last complete pass over the store.
 * @property {string|null} full_scan_at - End of the last successful full scan of the
 *   whole store; incremental scans trust known version directories, so this is the
 *   last check of their contents.
 * @property {number} slots
 * @property {number} versions
 * @property {number} missing_versions
 * @property {number} unlocated_versions - Versions without location.
 * @property {number} issues
 * @property {Job|null} last_scan - Last finished scan, with its actor.
 * @property {Job|null} running_job - A queued or running job.
 * @property {boolean} stale - Answers come from an index not refreshed.
 */

/**
 * A background job next to a store's state.
 *
 * @typedef {object} Job
 * @property {string} id
 * @property {string} kind - `scan`, `footprints` or `link_check`.
 * @property {string} state - `queued`, `running`, `succeeded`, `failed` or
 *   `interrupted`.
 * @property {string} actor - Who started it (`local`, an account, an agent).
 * @property {string} created_at
 * @property {string|null} started_at
 * @property {string|null} finished_at
 * @property {Progress|null} progress
 */

/**
 * Progress of a job: its last progress event (a scan counts segments).
 *
 * @typedef {object} Progress
 * @property {number} current
 * @property {number} total
 */

/**
 * A store for the „Magazyn” view: usage, clean-up report, projects, problems.
 *
 * @typedef {object} StoreDetail
 * @property {string} store
 * @property {string} name
 * @property {StoreKind} kind
 * @property {string[]} producers
 * @property {StoreState} state
 * @property {Usage} usage
 * @property {Unused} unused
 * @property {ProjectItem[]} projects - Projects naming the store that the principal
 *   sees.
 * @property {Issue[]} problems
 */

/**
 * Disk usage of a store: links add nothing, a content counts once.
 *
 * @typedef {object} Usage
 * @property {UsageRow[]} products
 * @property {number} versions
 * @property {number} unique_bytes
 */

/**
 * Disk usage of one product's present versions, each content once.
 *
 * @typedef {object} UsageRow
 * @property {string|null} product
 * @property {number} versions
 * @property {number} unique_bytes
 */

/**
 * Present versions neither current, a full sheet, nor pinned by any project.
 *
 * @typedef {object} Unused
 * @property {UsageRow[]} products
 * @property {number} versions
 * @property {number} unique_bytes
 * @property {number} reclaimable_bytes - Contents no other present version holds.
 */

/**
 * A visible store or project problem with a Polish fix instruction.
 *
 * @typedef {object} Issue
 * @property {string} code - Stable code: missing_sidecar, invalid_sidecar,
 *   unknown_segment, legacy_campaigns, stale_incoming, link_mismatch, orphan_sidecar,
 *   missing_pin, pin_sha256_mismatch, invalid_manifest, unknown_store…
 * @property {string} message - What is wrong, in Polish.
 * @property {string} instruction - How a person fixes it, in Polish.
 * @property {string|null} path - Store-relative path concerned.
 * @property {string|null} segment
 * @property {string|null} slot
 * @property {string|null} project - Project id of a project problem.
 * @property {string|null} task
 * @property {"scan"|"check"|null} origin - Found by a scan or by a check job.
 * @property {string|null} first_seen_at
 */

/**
 * A store answered from the index while it is unavailable.
 *
 * @typedef {object} StaleStore
 * @property {string} store - Store id.
 * @property {StoreStatus} status - `unavailable`.
 * @property {string|null} status_at - Since when.
 * @property {string|null} indexed_at - End of the last complete pass: the answer's
 *   state.
 * @property {string|null} detail - Why the store is unavailable.
 */

// Catalog, cards and map (9a) ------------------------------------------------

/**
 * @typedef {"current"|"all"|"full_sheet"|"pinned"|"noncurrent_unpinned"} VersionsMode
 */

/**
 * @typedef {"ok"|"missing"|"no_sidecar"|"unreadable"|"unrecognized"} RowStatus
 */

/**
 * @typedef {"any"|"with"|"none"} LocationFilter
 */

/**
 * @typedef {"footprint"|"country"|"none"} LocationKind
 */

/**
 * Filters shared by `GET /slots` and `GET /map/footprints` (unknown ones answer 400).
 *
 * @typedef {object} CommonFilters
 * @property {string} [q] - Search text; every word must match (unit, file name,
 *   segment and product name, version label, sha256 prefix…).
 * @property {string} [store] - Store id (/stores).
 * @property {string} [product] - Product (/products).
 * @property {string} [country] - Country code.
 * @property {string} [years] - Data year: `2023`, `2020-2023`, `2020-` or `-2023`.
 * @property {string} [unit] - Exact unit code of the slot: sheet, TERYT or KU.
 * @property {VersionsMode} [versions] - Default `current`.
 * @property {RowStatus} [status]
 */

/**
 * Parameters of `GET /slots` (catalog and search).
 *
 * @typedef {CommonFilters & {
 *   location?: LocationFilter,
 *   area_id?: string,
 *   bbox?: string,
 *   bbox_crs?: string,
 *   limit?: number,
 *   cursor?: string,
 * }} SlotFilters
 */

/**
 * Parameters of `GET /map/footprints`: `bbox` is the view `min_lon,min_lat,max_lon,
 * max_lat` (WGS84), `limit` ≤ 5000 outlines (above it a grid of `grid_columns`).
 *
 * @typedef {CommonFilters & {bbox: string, limit?: number, grid_columns?: number}}
 *   FootprintFilters
 */

/**
 * Parameters of `GET /map/sheets`.
 *
 * @typedef {object} SheetQuery
 * @property {string} bbox - The view `min_lon,min_lat,max_lon,max_lat` in WGS84.
 * @property {string} system - Sheet system of the producer, e.g. Kartograf's `1992`.
 * @property {string} scale - Sheet scale, e.g. `1:10000`.
 * @property {string} [producer] - Default `kartograf`.
 */

/**
 * A page of catalog rows; `next_cursor` continues it (keyset pagination).
 *
 * @typedef {object} CatalogPage
 * @property {boolean} stale - True when a store of the answer is unavailable: its rows
 *   are as of the store's `indexed_at`, not proof that files are gone.
 * @property {StaleStore[]} stale_stores - Unavailable stores of the answer; empty when
 *   it is current.
 * @property {SlotItem[]} items
 * @property {string|null} next_cursor - Opaque cursor of the next page of the same
 *   query; null on the last page. A cursor of other filters is rejected (400).
 * @property {LocationGroups} groups
 */

/**
 * Rows per location group over the whole result, whatever `location` is.
 *
 * @typedef {object} LocationGroups
 * @property {number} footprint - With an outline (in the area, with one).
 * @property {number} country - Whole-country files (of the area's countries).
 * @property {number} none - Without location: shown only in the catalog.
 */

/**
 * A catalog row: a slot (a file's place) with the version the query chose.
 *
 * @typedef {object} SlotItem
 * @property {string} store - Store id.
 * @property {string} slot - Slot path (the standard path) in the store.
 * @property {string} name - File name.
 * @property {Segment} segment
 * @property {string|null} unit - Unit code: sheet, TERYT or KU.
 * @property {string|null} product
 * @property {string|null} country
 * @property {RowStatus} status - `ok`, `missing`, `no_sidecar`, `unreadable` or
 *   `unrecognized`.
 * @property {Location} location
 * @property {Version|null} version - The row's version; null for a slot without a
 *   current one.
 * @property {number} versions_count - Versions of the slot in the index.
 */

/**
 * A store segment (product variant) with the producer's name for it.
 *
 * @typedef {object} Segment
 * @property {string|null} path - Segment path in the store; null for a producer without
 *   segments.
 * @property {string} label - Producer's human-readable name of the segment.
 * @property {string} producer - Producer id, e.g. `kartograf`.
 * @property {string|null} product - Product, e.g. `nmt`.
 * @property {string|null} country - Country code, e.g. `PL`.
 * @property {string|null} dataset_key - Producer's source key.
 * @property {boolean} known - Whether the producer recognises the segment.
 */

/**
 * Where a file is (A-ADR-022): an outline, a whole country, or nowhere.
 *
 * @typedef {object} Location
 * @property {LocationKind} kind - `footprint`, `country` or `none`.
 * @property {string|null} reason - Why `none`: `no_source` (no outline), `unreadable`,
 *   `pending` (not computed yet) or `no_current` (no current version).
 * @property {string|null} source - Origin of a footprint: `request`, `sheet`, `header`
 *   or `unit`.
 */

/**
 * Coordinate reference systems of a version.
 *
 * @typedef {object} Crs
 * @property {string|null} horizontal
 * @property {string|null} vertical
 */

/**
 * @typedef {"ok"|"missing"|"sha256_mismatch"|"unknown"} PinState
 */

/**
 * A project task pinning a version (`Przypięta w: Raba (teren)`).
 *
 * @typedef {object} Pin
 * @property {string} project - Project id, as in /projects/{project}.
 * @property {string} name - Project name.
 * @property {string|null} task - Task of the project.
 * @property {string|null} sha256 - Content the project pinned.
 * @property {PinState} state - `ok`; `missing` (not in the store); `sha256_mismatch`
 *   (other content); `unknown` (the project's store is not configured).
 */

/**
 * @typedef {"present"|"missing"} VersionState
 */

/**
 * A version of a file: an immutable copy under `versions/`.
 *
 * @typedef {object} Version
 * @property {string} path - Version path in the store.
 * @property {string} ref - Reference of the version (`version:<store>:<path>`) for its
 *   previews, `archiwista preview` and comparisons; copy it, never compose it.
 * @property {string|null} label - Version label, e.g. `2025-04-26_82710`.
 * @property {string|null} label_source - What the label is: `campaign`, `edition` or
 *   `downloaded`.
 * @property {number|null} data_year - Year of the data (flight, edition) — never the
 *   download year.
 * @property {string|null} data_date - Date of the data.
 * @property {string|null} downloaded_at - When it was downloaded.
 * @property {string|null} sha256
 * @property {number|null} size_bytes
 * @property {boolean|null} full_sheet - Producer's claim that the sheet is complete.
 * @property {Crs} crs
 * @property {boolean} is_current - Held by the slot's standard path.
 * @property {boolean} is_full_sheet - Held by the slot's `full_sheet/` link.
 * @property {VersionState} state - `present` or `missing` from the store.
 * @property {string|null} missing_since
 * @property {Location} location
 * @property {Pin[]} pinned_by - Pins of projects the session's principal sees.
 */

/**
 * Where the file is on this computer and on aliased ones (SPEC 4.6).
 *
 * @typedef {object} CopyPath
 * @property {string} local - Absolute path on this computer.
 * @property {string[]} aliases - The same file as mounted on other computers (path
 *   aliases).
 */

/**
 * File card: every version of a slot, current and full sheet, pins, problems.
 *
 * @typedef {object} SlotCard
 * @property {boolean} stale - True when a store of the answer is unavailable: its rows
 *   are as of the store's `indexed_at`, not proof that files are gone.
 * @property {StaleStore[]} stale_stores - Unavailable stores of the answer; empty when
 *   it is current.
 * @property {string} store
 * @property {string} slot
 * @property {string} name
 * @property {Segment} segment
 * @property {string|null} unit
 * @property {string|null} product
 * @property {string|null} country
 * @property {RowStatus} status
 * @property {string|null} current - Path of the current version.
 * @property {string|null} full_sheet - Path of the `full_sheet/` version.
 * @property {CopyPath|null} paths - Copy path of the standard path; null if the store
 *   is gone.
 * @property {Version[]} versions - Every version, by path.
 * @property {Issue[]} problems
 */

/**
 * Every indexed value of one version, its raw sidecar and copy path.
 *
 * @typedef {object} VersionCard
 * @property {boolean} stale - True when a store of the answer is unavailable: its rows
 *   are as of the store's `indexed_at`, not proof that files are gone.
 * @property {StaleStore[]} stale_stores - Unavailable stores of the answer; empty when
 *   it is current.
 * @property {string} store
 * @property {string} slot
 * @property {string} ref - Reference of the version (`version:<store>:<path>`).
 * @property {Segment} segment
 * @property {Version} version
 * @property {string|null} dataset
 * @property {string|null} dataset_key
 * @property {string|null} product
 * @property {string|null} country
 * @property {string|null} unit
 * @property {string|null} campaign
 * @property {string|null} survey_work_id - Survey work (request) number.
 * @property {string|null} edition
 * @property {number|null} coverage - Share of the sheet with data, 0–1.
 * @property {string|null} parent_request - Key of the producer request; files of one
 *   request: /requests/{key}.
 * @property {string|null} license
 * @property {string|null} attribution
 * @property {string[]} source_files - Store paths of the input versions of a derived
 *   file.
 * @property {string|null} resolution
 * @property {number|null} nodata
 * @property {string|null} native_crs - CRS of the native outline.
 * @property {Geometry|null} footprint - Outline: GeoJSON in WGS84.
 * @property {boolean} has_meta - Whether a readable sidecar was indexed.
 * @property {CopyPath|null} paths - Copy path of this version; null if the store is
 *   gone.
 * @property {Object<string, *>|null} sidecar - The producer's raw sidecar, unchanged;
 *   null without one.
 */

/**
 * A file of one producer request (e.g. both sides of a border).
 *
 * @typedef {object} RequestFile
 * @property {string} store
 * @property {string} slot
 * @property {string} version - Version path.
 * @property {string|null} segment
 * @property {string|null} country
 * @property {string|null} label
 * @property {boolean} is_current
 */

/**
 * Files of one producer request (`parent_request`).
 *
 * @typedef {object} RequestFiles
 * @property {boolean} stale
 * @property {StaleStore[]} stale_stores
 * @property {string} parent_request
 * @property {RequestFile[]} items
 */

/**
 * An indexed segment (variant) of a product in one store.
 *
 * @typedef {object} ProductSegment
 * @property {string} store
 * @property {Segment} segment
 * @property {number} slots
 * @property {number} versions
 */

/**
 * An indexed product with its segments; names come from the producer.
 *
 * @typedef {object} Product
 * @property {string|null} product - Product, e.g. `nmt`; null for segments not
 *   recognised.
 * @property {string[]} countries
 * @property {number} slots
 * @property {number} versions
 * @property {ProductSegment[]} segments
 */

/**
 * Products in the index: only what was scanned, nothing guessed.
 *
 * @typedef {object} ProductList
 * @property {boolean} stale
 * @property {StaleStore[]} stale_stores
 * @property {Product[]} items
 */

/**
 * A GeoJSON geometry in WGS84 (`Polygon`, `MultiPolygon`…).
 *
 * @typedef {{type: string, coordinates: Array<*>}} Geometry
 */

/**
 * One outline drawn on the map.
 *
 * @typedef {object} Footprint
 * @property {string} store
 * @property {string} slot
 * @property {string} version
 * @property {string|null} segment
 * @property {string|null} product
 * @property {string|null} label
 * @property {number|null} data_year
 * @property {string|null} source - Origin of the outline.
 * @property {Geometry} geometry - GeoJSON in WGS84.
 */

/**
 * Number of footprints whose centre falls in one grid cell (WGS84).
 *
 * @typedef {object} Cell
 * @property {number} min_lon
 * @property {number} min_lat
 * @property {number} max_lon
 * @property {number} max_lat
 * @property {number} count
 */

/**
 * Footprints of a map view or, above `limit`, their grid.
 *
 * @typedef {object} MapView
 * @property {boolean} stale
 * @property {StaleStore[]} stale_stores
 * @property {number} total - Footprints in the view.
 * @property {boolean} aggregated - True: `cells` instead of `items`.
 * @property {Footprint[]} items
 * @property {Cell[]} cells
 * @property {LocationGroups} groups - Catalog counts of the same filters without the
 *   view: `none` is the 'files without outline' counter leading to the catalog.
 */

/**
 * A sheet of a map sheet grid with its zone and outline.
 *
 * @typedef {object} Sheet
 * @property {string} sheet - Sheet code (godło).
 * @property {number|null} zone - PL-2000 zone (5-8) of the powiats the sheet lies over;
 *   `null` in PL-1992.
 * @property {Geometry} geometry - GeoJSON Polygon or MultiPolygon in WGS84: the sheet, or
 *   the part of a PL-2000 sheet inside its zone where a zone boundary cuts it.
 */

/**
 * Sheets of a sheet system and scale in a map view.
 *
 * @typedef {object} SheetList
 * @property {string} producer
 * @property {string} system
 * @property {string} scale
 * @property {"available"|"unsupported"} status - `unsupported` for a producer without
 *   sheet grids.
 * @property {Sheet[]} items
 */

// Projects (9a) --------------------------------------------------------------

/**
 * One producer's manifest in a project directory, as the last scan read it.
 *
 * @typedef {object} ProjectManifest
 * @property {string} producer - `kartograf` (`kartograf-project.json`) or `imgw`
 *   (`imgw-project.json`).
 * @property {string|null} store - Configured store the manifest names; null when none
 *   matches.
 * @property {string|null} status - Producer's status when the manifest was read: `ok`,
 *   `not_downloaded`, `missing` or `corrupt`; null when not checked.
 * @property {string|null} problem - Producer's message for an invalid manifest, whose
 *   tasks and pins are not read; the other manifest is read all the same.
 * @property {string} scanned_at - When the manifest was read.
 */

/**
 * A discovered project the session's principal sees: a directory with the manifest
 * of one producer or of both.
 *
 * @typedef {object} ProjectItem
 * @property {string} project - Project id: /projects/{project}.
 * @property {string} name
 * @property {ProjectManifest[]} manifests - Kartograf's first.
 * @property {number} tasks - Tasks of every manifest.
 * @property {number} pins - Pins of every manifest.
 * @property {number} missing_pins - Pins missing from the store or other.
 * @property {boolean} project_write - Whether the session's principal may change the
 *   project now (its owner or an administrator): add and remove its tasks, and download
 *   and repin it with `store_write` of the session.
 */

/**
 * Projects the session's principal sees, ordered by name.
 *
 * @typedef {object} ProjectList
 * @property {boolean} stale
 * @property {StaleStore[]} stale_stores
 * @property {ProjectItem[]} items
 */

/**
 * A task of a project's manifest with its existing command and options.
 *
 * @typedef {object} ProjectTask
 * @property {string} producer - Producer of the manifest holding the task.
 * @property {string} task
 * @property {string} command - Producer command as in the manifest.
 * @property {Object<string, *>} options - Options as in the manifest.
 * @property {string|null} status
 */

/**
 * A version a project task pinned (older versions too).
 *
 * @typedef {object} ProjectPin
 * @property {string} producer - Producer of the manifest that pins it.
 * @property {string|null} task
 * @property {string} version - Pinned version path, relative to the producer's
 *   directory.
 * @property {string|null} sha256
 * @property {PinState} state
 * @property {string|null} slot
 * @property {string|null} label
 * @property {number|null} size_bytes
 * @property {boolean} is_current
 */

/**
 * A project: its manifests, tasks with their commands, pinned versions and problems.
 *
 * @typedef {object} ProjectCard
 * @property {boolean} stale
 * @property {StaleStore[]} stale_stores
 * @property {string} project - Project id: /projects/{project}.
 * @property {string} name
 * @property {ProjectManifest[]} manifests - Kartograf's first.
 * @property {number} missing_pins - Pins missing from the store or other.
 * @property {boolean} project_write - As in `ProjectItem`.
 * @property {ProjectTask[]} tasks - Tasks of each manifest in its order.
 * @property {ProjectPin[]} pins - Pinned versions, older ones too.
 * @property {Issue[]} problems - Invalid manifest, unknown store, a task name in the
 *   manifests of several producers (`duplicate_task`), missing or other pinned files.
 */

/**
 * A task's state as the producer checked it.
 *
 * @typedef {object} TaskStatus
 * @property {string} task
 * @property {string|null} status - `ok`, `not_downloaded`, `missing` or `corrupt`
 *   (worst file).
 */

/**
 * A producer's check of its manifest of a project now.
 *
 * @typedef {object} ManifestStatus
 * @property {string} producer
 * @property {string|null} status - The worst task status.
 * @property {string} checked_at - When the producer checked: now, or the last scan when
 *   stale.
 * @property {boolean} stale - True: the store is unavailable, the scan's check is
 *   shown.
 * @property {string|null} stale_reason
 * @property {TaskStatus[]} tasks
 */

/**
 * The producers' checks of a project now (no network, no hashing).
 *
 * @typedef {object} ProjectStatus
 * @property {string} project
 * @property {ManifestStatus[]} manifests - In the order of the project's manifests.
 */

/**
 * Body of `POST /projects`: a new project of a producer bound to a configured store.
 *
 * @typedef {object} ProjectRequest
 * @property {string} producer - Producer that writes the project's manifest, e.g.
 *   `kartograf`.
 * @property {string} path - Absolute path of the project directory, made when missing: a
 *   project directory of the settings or a directory at most four levels below one, in no
 *   hidden directory and no store, where a scan finds it.
 * @property {string} store - Id of the configured store whose directory of the producer
 *   the manifest names.
 */

/**
 * Body of `POST /projects/{project}/tasks`: a task added by the project's producer.
 *
 * @typedef {object} TaskRequest
 * @property {string} name - Name of the new task; the producer's rules apply.
 * @property {string} command - Data command of the producer's catalog.
 * @property {Object<string, *>} [options] - Its options in the JSON form of the catalog,
 *   checked without the network; no option that is a file path.
 * @property {string} [producer] - The producer whose manifest gets the task; left out:
 *   the project's only one (needed for a project of several).
 */

/**
 * Body of `POST /projects/{project}/jobs`: a job of a project's tasks.
 *
 * @typedef {object} ProjectJobRequest
 * @property {"download"|"repin"|"check"|"verify"} kind - `download` and `repin` write
 *   the store and the manifest (`project_write` and `store_write`); `check` and `verify`
 *   need only to see the project; all but `verify` use the network.
 * @property {string[]} [tasks] - The tasks by name; left out: every task. A `repin` names
 *   exactly one.
 * @property {string} [producer] - The producer whose manifest's tasks run; left out: the
 *   project's only one (needed for a project of several).
 */

// Settings (9a) --------------------------------------------------------------

/**
 * A configured store: a short id and the producers' directories.
 *
 * @typedef {object} StoreSettings
 * @property {string} id - Short id in the API: lowercase letters, digits, '_', '-' (≤
 *   32).
 * @property {string} name
 * @property {string|null} [kartograf] - Kartograf's store root: the directory that holds
 *   `kartograf-store.json` and the product directories (usually called `data`); null when
 *   the store has only `imgw`.
 * @property {string|null} [imgw] - IMGWTools' store root, the directory with
 *   `imgw-store.json`; null when the store has only `kartograf`. One of the two is
 *   required.
 * @property {StoreKind|null} [kind] - `local` or `share`; detected from the file system
 *   when omitted.
 * @property {Object<string, string>} [path_aliases] - Local path prefix → the same
 *   share's prefix on another computer.
 */

/**
 * An online basemap, used only when offline mode is off.
 *
 * @typedef {object} BasemapSettings
 * @property {string} name
 * @property {"xyz"|"wms"|"vector"} [kind] - `xyz` raster tiles, `wms`, or `vector`: the
 *   TileJSON of OpenMapTiles vector tiles, drawn in Archiwista's grey style with
 *   Polish names.
 * @property {string} url - Tile template with {z}/{x}/{y}, a WMS address, or a TileJSON
 *   address (its tiles on the same origin).
 * @property {string} [attribution]
 * @property {boolean} [grayscale] - Raster tiles in grey.
 */

/**
 * All settings; PUT replaces all of them (omitted fields take defaults).
 *
 * @typedef {object} Settings
 * @property {number} [port] - Port on 127.0.0.1.
 * @property {boolean} [offline] - No external request from the browser (no online
 *   basemaps).
 * @property {number} [scan_threads] - Threads reading a store on a share.
 * @property {number} [scan_interval_local_min]
 * @property {number} [scan_interval_share_min]
 * @property {number} [full_scan_interval_h] - Hours between scheduled full control
 *   scans; only a full scan notices files deleted or added inside known version
 *   directories.
 * @property {string[]} [project_dirs] - Absolute directories searched for projects.
 * @property {StoreSettings[]} [stores]
 * @property {BasemapSettings[]} [basemaps] - Grey OpenFreeMap (vector) and OSM GUGiK
 *   (raster, Poland only) when omitted.
 * @property {boolean} [store_write_for_all] - Everyone may write to stores, not only
 *   `store_writer` (v0.3).
 * @property {"public"|"private"} [default_project_visibility] - Visibility of a project
 *   without its own access entry.
 * @property {number} [preview_cache_limit_gb] - Preview cache limit in GB (1024³ bytes),
 *   1–10 000; the least recently used previews go first.
 * @property {boolean} [preview_warm_after_scan] - After a scan that indexed new versions
 *   of a store, prepare the first look at them (a `preview_warm` job); off by default.
 */

// Background jobs (9b) -------------------------------------------------------

/**
 * Why a job ended without success.
 *
 * @typedef {object} JobFailure
 * @property {string} code - A code of the error registry, as in a problem:
 *   store_unavailable, missing_dependency, conflict, forbidden, data_error, not_found,
 *   unsupported, cancelled, internal_error.
 * @property {string} detail - Polish description.
 * @property {string|null} hint - Polish line telling how to fix it.
 * @property {ProblemDetails} details - The reason (`reason`: store_unreadable,
 *   source_unavailable, offline_mode, snapshot_blocked, inconsistent_copy,
 *   path_outside_root, kartograf_error, interrupted, worker_crashed…) and the
 *   context (`blocked_by` of a blocked snapshot).
 */

/**
 * A background job: `202` of POST …/scan, …/footprints, …/link-check, …/preview,
 * `/projects/{project}/scan`, …/snapshots and `/projects/{project}/jobs`, `GET
 * /jobs/{job}` and the items of `GET /jobs`.
 *
 * @typedef {object} JobDetail
 * @property {string} id
 * @property {"scan"|"footprints"|"link_check"|"preview"|"own_scan"|"snapshot"
 *   |"availability"|"check"|"download"|"project_download"|"project_repin"
 *   |"project_check"|"project_verify"|"preview_warm"} kind
 * @property {"queued"|"running"|"succeeded"|"partial"|"failed"|"interrupted"|"cancelled"} state -
 *   `partial`: part of its units failed, `result` names them.
 * @property {string} actor - Who started it.
 * @property {"local_owner"|"user"|"agent"|"scheduler"} actor_kind - How: the owner, an
 *   account, an agent for `actor`, or the scheduler.
 * @property {string|null} session - Label of the session it was started in.
 * @property {string|null} store - Null for `preview`, `own_scan`, `snapshot`,
 *   `availability`, the `project_*` kinds and `preview_warm`.
 * @property {Object<string, *>} params - `mode`/`segment` of a scan, `slot` of a link
 *   check, `refs` of a preview, `project` of an `own_scan` (none: every project),
 *   `project`, `file_id` and `note` of a snapshot, `area_id`, `producer`, `product`
 *   and `force` of an availability check, `producer` and `calls` (each `command` and
 *   `options`, in their order; all the lines of a row, ADR-044) of a plan (`check`),
 *   those and `plan_job` of a `download`, `project` and `tasks`
 *   (null: every task) of the `project_*` kinds, `store`, `product`, `segment`,
 *   `project`, `area_id` and `since` (null: not given) of a `preview_warm`.
 * @property {string} created_at
 * @property {string|null} started_at
 * @property {string|null} finished_at
 * @property {Object<string, *>|null} progress - Data of the last progress event:
 *   `current` of `total`; an `own_scan` adds `files` and `read`, a snapshot its `phase`
 *   (`copy`, `checksums`, `document`, `rename`, `published`), a `check` counts the
 *   calls it planned, a `download` counts the units of the call it runs and adds
 *   `call` (its place, from 0) and `calls` (their number), the three of a
 *   `download`, a `project_download` and a `project_repin` add the producer's
 *   `unit` (or null), `status` and `message`, a `preview_warm` `warmed`, `cached`,
 *   `failed` and `skipped`.
 * @property {Object<string, *>|null} result - Summary of a job that succeeded or ended
 *   `partial`; of an `own_scan` the counts `projects`, `files`, `new`, `changed`,
 *   `missing`, `unreadable`, `snapshots`, `problems`, `seconds`; of a snapshot
 *   `status` (`created` or `unchanged`), `label`, `content_sha256`, `size_bytes`,
 *   `seconds`; of an availability check `area_id`, `producer`, `product`,
 *   `checked_at`, `ok`, `combinations`, `kept`, `seconds`; of a plan (`check`)
 *   `producer`, `store`, `root`, `checked_at` (of the oldest plan), `ok`, `positions`,
 *   `counts`, `size_bytes` (null: no size known), `size_complete`, `failed` (`call`,
 *   `path`, `error`), `calls` (per call in its order: `command`, `line`, `status`
 *   `ok`, `partial` or `failed`, `positions`, `todo`, `error` `{code, reason,
 *   detail}` or null), `seconds`; of a `download` `producer`, `store`, `root`,
 *   `plan_job`, `status` (`ok`, `partial`), `counts` of the files (`new`,
 *   `unchanged`, `relabeled`), `files` (`path`, `version_path`, `unit`, `status`,
 *   `size_bytes`, `sha256`, `label`, `call`), `items` (`id`, `status`, `code`,
 *   `reason`, `message`, `call`), `failed`, `calls` (per call: `command`, `line`,
 *   `status` `ok`, `partial`, `failed` or `skipped`, `reason` of a skipped one
 *   `not_planned` or `nothing_to_download`, `files`, `failed`, `error`),
 *   `rescanned`, `seconds`; of a `project_download` or `project_repin`
 *   `producer`, `project`, `store`, `root`, `upgrade`, `ok`, `counts` of the tasks
 *   (`pinned`, `unchanged`, `restored`, `updated`, `failed`), `tasks` (`name`,
 *   `outcome`, `pinned`, `unpinned`, `errors`, `code`, `reason`), `failed`,
 *   `rescanned`, `seconds`; of a `project_check` or `project_verify` `producer`,
 *   `project`, `root`, `ok`, `counts` of the files, `files` (`task`, `unit`,
 *   `path`, `status`, `pinned_label`, `available_label`, `detail`),
 *   `not_downloaded`, `seconds`; of a `preview_warm` `versions`, `files`,
 *   `warmed`, `cached`, `needs_build`, `failed`, `failures` (`ref`, `code`,
 *   `detail`), `skipped`, `stopped` (`cache_full` or null), `room_bytes`,
 *   `seconds`.
 * @property {JobFailure|null} error
 */

/**
 * A page of jobs, newest first.
 *
 * @typedef {object} JobList
 * @property {JobDetail[]} items
 * @property {string|null} next_cursor
 */

/**
 * Parameters of `GET /jobs`.
 *
 * @typedef {object} JobFilters
 * @property {string} [kind]
 * @property {string} [store]
 * @property {string} [state]
 * @property {string} [project] - Only jobs with this project's data (its own-data
 *   scans, snapshots, previews of its files).
 * @property {number} [limit] - 1–200, default 50.
 * @property {string} [cursor]
 */

/**
 * Body of `POST /stores/{store}/scan`.
 *
 * @typedef {object} ScanRequest
 * @property {"incremental"|"full"} [mode] - Default `incremental`.
 * @property {string} [segment] - Only this segment (Kartograf: `<product>/<variant>`);
 *   a data source that reads only its whole directory (IMGWTools) fails the job as
 *   `unsupported`.
 */

/**
 * Handlers of a job's event stream (`GET /jobs/{job}/events`, SSE).
 *
 * @typedef {object} JobHandlers
 * @property {(data: {current: number, total: number}) => void} [onProgress] - A scan
 *   adds `segment` and `entries`, footprints `written` and `failed`.
 * @property {(data: {level: "info"|"warning", code: string, message: string}) => void}
 *   [onNotice] - A Polish message of the job.
 * @property {(data: {state: string, result?: Object<string, *>, error?: JobFailure})
 *   => void} [onState] - A new state; the stream ends after a final one.
 * @property {(problem: Problem) => void} [onError] - The stream broke off before a
 *   final state.
 */

// Areas and local coverage (9c) ----------------------------------------------

/**
 * Body of `POST /areas` as JSON.
 *
 * @typedef {object} AreaInput
 * @property {Geometry} geometry - GeoJSON `Polygon` or `MultiPolygon` in WGS84.
 * @property {string} [name]
 * @property {"drawn"|"view"|"sheet"} [source] - Default `drawn`.
 */

/**
 * An area kept by the server; the same geometry always has the same id.
 *
 * @typedef {object} Area
 * @property {string} id
 * @property {string|null} name
 * @property {"drawn"|"view"|"sheet"|"file"} source
 * @property {Geometry} geometry - GeoJSON in WGS84.
 * @property {number[]} bbox - `[min_lon, min_lat, max_lon, max_lat]`.
 * @property {number|null} area_km2 - Area in the planar CRS of its country.
 * @property {string|null} area_crs - `EPSG:2180` (PL) or `EPSG:5514` (CZ).
 * @property {string[]} countries
 * @property {string} created_at
 */

/**
 * Local coverage of an area in one country.
 *
 * @typedef {object} CountryCoverage
 * @property {string|null} country
 * @property {string|null} crs - Planar CRS of the computation.
 * @property {number|null} ratio - 0–1.
 * @property {number|null} percent - Rounded down; 100 only when fully covered.
 * @property {number|null} area_km2
 * @property {number|null} covered_km2
 * @property {number} versions_count
 * @property {"no_planar_crs"|"empty_area"|null} reason - Why there is no percent.
 * @property {string} label - Polish, e.g. „lokalnie 83% obszaru”.
 */

/**
 * Local coverage of an area by a product's current versions (`GET /local-coverage`).
 *
 * @typedef {object} AreaCoverage
 * @property {{id: string, name: string|null, area_km2: number|null, countries:
 *   string[]}} area
 * @property {string} store
 * @property {string} product
 * @property {string|null} segment
 * @property {CountryCoverage[]} results - Empty when the store has no version of the
 *   product for the area.
 * @property {boolean} stale
 * @property {"store_unavailable"|"refresh_timeout"|"too_many_slots"|null} stale_reason
 * @property {StaleStore[]} stale_stores
 */

/**
 * Parameters of `GET /local-coverage`.
 *
 * @typedef {object} LocalCoverageQuery
 * @property {string} area_id
 * @property {string} product
 * @property {string} store
 * @property {string} [segment]
 */

// Previews (v0.2, step 6) ----------------------------------------------------

/**
 * @typedef {"raster"|"image"|"vector"|"points"|"archive"|"document"|"auxiliary"|"unknown"}
 *   PreviewKind
 */

/**
 * @typedef {"ready"|"needs_build"|"building"|"unavailable"|"failed"} PreviewState
 */

/**
 * @typedef {"hillshade"|"hypsometry"|"rgb"|"gray"|"classes"|"features"|"elevation"}
 *   StyleName
 */

/**
 * Why a file has no preview, or no map preview.
 *
 * @typedef {object} PreviewReasonInfo
 * @property {string} code - Stable code: no_georeference, no_crs, auxiliary_file,
 *   archive_members_only, document_no_preview, unsupported_format, too_large,
 *   missing_file, store_unavailable, transform_unavailable, unreadable, timeout,
 *   memory_limit or changed_since_scan.
 * @property {string} message - What is missing and why, in Polish.
 * @property {string} fix - What a person can do about it, in Polish.
 * @property {string|null} detail - The library's own message (no paths), only in the
 *   answer that found it.
 */

/**
 * Colours from `min` to `max` of continuous values (hypsometry, elevation).
 *
 * @typedef {object} GradientLegend
 * @property {"gradient"} kind
 * @property {number} min
 * @property {number} max
 * @property {string|null} unit - Unit of the values, e.g. `m`.
 * @property {string[]} colors - Colours of the ramp from `min` to `max`, evenly spaced,
 *   `#rrggbb`.
 */

/**
 * Classes with their colours (CORINE, HSG, a palette of the file).
 *
 * @typedef {object} ClassesLegend
 * @property {"classes"} kind
 * @property {Array<{value: number, color: string, label: string}>} items - `color`
 *   `#rrggbb`; `label` the Polish name of the class, else the value.
 */

/**
 * A layer of a vector file.
 *
 * @typedef {object} VectorLayer
 * @property {string|null} name - Null for a layer named after its file (Shapefile,
 *   GeoJSON, FlatGeobuf).
 * @property {string|null} geometry_type - OGR's name, e.g. `LineString`; null for a
 *   table without geometry.
 * @property {number|null} feature_count
 * @property {Array<{name: string, type: string}>} fields - `type` as OGR names it,
 *   e.g. `String`, `Integer64`.
 * @property {string|null} crs
 * @property {number[]|null} bbox - In the layer's CRS.
 * @property {number[]|null} bbox_wgs84
 * @property {Array<Object<string, *>>|null} sample - At most 20 rows; `null` for NULL,
 *   binary and infinite values, long texts shortened with „…”.
 */

/**
 * Header, density and classes of a point cloud (LAZ, LAS).
 *
 * @typedef {object} PointCloud
 * @property {string} version - LAS version, e.g. `1.4`.
 * @property {number} point_format
 * @property {number} point_count
 * @property {boolean} compressed - LAZ.
 * @property {number[]} min - X, Y, Z.
 * @property {number[]} max - X, Y, Z.
 * @property {number|null} density_per_m2 - Only in a planar CRS.
 * @property {string|null} creation_date
 * @property {string|null} generating_software
 * @property {Array<{value: number, label: string, count: number}>} classes - ASPRS
 *   classes of the sample, Polish labels.
 * @property {number} sample_points
 * @property {"all"|"spread"|"start"} sampled_from - The whole cloud, a sample spread
 *   along the file, or its start (a LAZ without a chunk table).
 */

/**
 * The preview of one object (`GET …/preview`): state, reason, styles, legends,
 * addresses of its images (built by the server, never by the client) and build.
 *
 * @typedef {object} PreviewInfo
 * @property {string} ref - The object (`version:<store>:<path>`).
 * @property {PreviewState} state - `ready`, `needs_build` (map tiles need a local
 *   preview first; with `auto_build` the interface builds it at once), `building`
 *   (`job` builds it), `unavailable` (nothing to show: `reason`) or `failed` (a time
 *   or memory limit: try again later).
 * @property {PreviewKind} kind
 * @property {PreviewReasonInfo|null} reason - Why something is missing (no map, no
 *   preview).
 * @property {StyleName[]} styles - Styles of the thumbnail and tiles; empty without
 *   them.
 * @property {StyleName|null} default_style
 * @property {string|null} thumbnail_url - PNG thumbnail; add `style`, `size` (128,
 *   256, 512, 1024), `bbox`, `bbox_crs`.
 * @property {string|null} tiles_url - `{z}/{x}/{y}` template within `minzoom`–`maxzoom`
 *   and `bounds`; add `style`, `rescale`.
 * @property {string|null} features_url - Template with `{bbox}` and `{zoom}`; add
 *   `layer`, `limit`.
 * @property {string|null} members_url - Members of an archive (`ArchiveMembers`).
 * @property {number[]|null} bounds - WGS84: west, south, east, north.
 * @property {number|null} minzoom
 * @property {number|null} maxzoom
 * @property {GradientLegend|ClassesLegend|null} legend - Legend of the default style.
 * @property {Object<string, GradientLegend|ClassesLegend>} legends - Legend of every
 *   style that has one, by style.
 * @property {VectorLayer[]} layers
 * @property {PointCloud|null} points
 * @property {number|null} size_bytes
 * @property {boolean} auto_build - Whether the build starts at the first view (a file
 *   of at most 2 GB, a raster of at most 1 Gpx and 8 GB unpacked).
 * @property {{id: string, state: string}|null} job - The `preview` job building it.
 */

/**
 * A member of a ZIP archive, as its central directory lists it.
 *
 * @typedef {object} ArchiveMember
 * @property {string} name - Name in the archive (not unpacked).
 * @property {number} size_bytes
 * @property {number} compressed_bytes
 * @property {boolean} directory
 * @property {string} format - Format by the name's extension.
 * @property {PreviewKind} kind
 */

/**
 * Members of an archive, read without unpacking it (`members_url`).
 *
 * @typedef {object} ArchiveMembers
 * @property {string} ref
 * @property {number} total - Members the archive declares.
 * @property {boolean} truncated - More than the first 10 000 are not listed.
 * @property {ArchiveMember[]} members
 */

/**
 * The preview cache against its limit, and the render processes (`/health`).
 *
 * @typedef {object} PreviewsState
 * @property {number} used_bytes - Bytes of the preview cache.
 * @property {number} limit_bytes - Its limit (`preview_cache_limit_gb`).
 * @property {number} objects - Objects: previews of one content each.
 * @property {number} workers - Render processes at most.
 */

/**
 * The features of a map view (`features_url`): GeoJSON in WGS84, simplified to
 * the view's zoom.
 *
 * @typedef {object} PreviewFeatures
 * @property {"FeatureCollection"} type
 * @property {Array<{type: "Feature", geometry: Geometry|null,
 *   properties: Object<string, *>}>} features
 * @property {string|null} layer - The layer read.
 * @property {number|null} number_matched - Null past `limit`.
 * @property {number} number_returned
 * @property {boolean} truncated - More than `limit` features or 500 000 vertices:
 *   zoom in or open the file in QGIS.
 * @property {boolean} simplified - Some geometry lost vertices.
 */

// Local layers (v0.2, step 11) -----------------------------------------------

/**
 * Parameters of `GET /local-layers`.
 *
 * @typedef {object} LayersQuery
 * @property {string} store
 * @property {string} product
 * @property {string} [area_id] - Without one, only the counts of every layer.
 * @property {string} [segment]
 * @property {"year"|"campaign"} [group]
 */

/**
 * The variant of a layer: no file format in it (A-ADR-017).
 *
 * @typedef {object} LayerVariant
 * @property {string|null} product
 * @property {string|null} horizontal_crs
 * @property {string|null} resolution
 * @property {string|null} vertical_crs
 * @property {string[]} segments
 * @property {string[]} formats - Badges, e.g. `ASCII Grid`.
 */

/**
 * The previews of a layer's versions and the addresses of its images.
 *
 * @typedef {object} LayerPreview
 * @property {PreviewState} state - `ready`, `building` (`job` builds the missing
 *   ones), `needs_build` without a job, `unavailable` (nothing to show on a map).
 * @property {number} ready - Versions with a ready preview.
 * @property {number} total - Versions that can have one.
 * @property {{id: string, state: string}|null} job
 * @property {string|null} thumbnail_url - The layer's image in the frame.
 * @property {string|null} tiles_url - One raster source of map tiles (`{z}/{x}/{y}`).
 * @property {number|null} minzoom - Below it the tiles are `404`: show the outlines.
 */

/**
 * A version of a layer in the area.
 *
 * @typedef {object} LayerVersion
 * @property {string} ref - `version:<store>:<path>`; of an own file's layer `file:` or
 *   `snapshot:`.
 * @property {string} slot - Slot path; of an own file's layer its path in the data
 *   folder.
 * @property {string|null} unit
 * @property {{state: PreviewState, tiles_url: string|null}} preview
 * @property {number[]|null} bounds - WGS84: west, south, east, north.
 */

/**
 * A layer: a variant's data year, edition, label or campaign.
 *
 * @typedef {object} Layer
 * @property {string} key - `<variant>:<year|edition|label>[:<campaign>]` (`layer` of
 *   the address); of an own file's layers `file` or `snapshot:<label>`.
 * @property {LayerVariant} variant
 * @property {"year"|"edition"|"label"|"campaign"|"file"|"snapshot"} kind
 * @property {number|null} year - Data year, never the download's.
 * @property {string} title - Polish, e.g. `2023` or `wydanie 2021`.
 * @property {string} subtitle - The variant's name.
 * @property {number} versions_count
 * @property {number} units_count
 * @property {string[]} campaigns
 * @property {string[]} data_dates
 * @property {{ratio: number|null, percent: number|null, label: string}|null} coverage
 * @property {Object<string, *>|null} outlines - GeoJSON in `frame.crs` (planar).
 * @property {LayerPreview|null} preview - With an area only.
 * @property {LayerVersion[]|null} versions - At most 500, with an area only.
 */

/**
 * Layers of a store's product, newest first (`GET /local-layers`).
 *
 * @typedef {object} LayerSet
 * @property {{id: string, name: string|null, area_km2: number|null, countries:
 *   string[]}|null} area
 * @property {string|null} store - Null for an own file's layers
 *   (`/projects/{project}/files/{file_id}/layers`), as `product` and `group`.
 * @property {string|null} product
 * @property {string|null} segment
 * @property {"year"|"campaign"|null} group
 * @property {{crs: string, bbox: number[]}|null} frame - The area's box in its planar
 *   CRS.
 * @property {Layer[]} layers
 * @property {boolean} stale
 * @property {"store_unavailable"|"refresh_timeout"|"too_many_slots"|null} stale_reason
 * @property {StaleStore[]} stale_stores
 */

// Comparison (v0.2, step 10) -------------------------------------------------

/**
 * One compared object (`Comparison.a`, `Comparison.b`).
 *
 * @typedef {object} ComparisonSide
 * @property {string} ref - `version:<store>:<path>`, `file:` or `snapshot:`.
 * @property {"version"|"file"|"snapshot"} kind
 * @property {string} title - For people, e.g. `N-34-130-D-d-2-4.asc — 2019-07-12_41022`.
 * @property {string|null} preview - Address of its preview description (`…/preview`,
 *   a `PreviewInfo`); `POST` to it builds the local preview.
 * @property {Geometry|null} outline - WGS84.
 */

/**
 * One field of both objects.
 *
 * @typedef {object} ComparisonRow
 * @property {"metadata"|"sidecar"|"own"|"layers"} group - `metadata`: a normalized
 *   field of a store version; `sidecar`: a raw sidecar's field named by its JSON path;
 *   `own` and `layers`: an own file's or a snapshot's field and objects per layer.
 * @property {string} field - Field id (the JSON path in `sidecar`).
 * @property {string} label - Human name of the field.
 * @property {string|number|boolean|null} a - Value of A (dates as ISO text).
 * @property {string|number|boolean|null} b
 * @property {boolean} differs
 */

/**
 * Metadata of two objects side by side (`GET /compare?a&b`, level 1).
 *
 * @typedef {object} Comparison
 * @property {ComparisonSide} a
 * @property {ComparisonSide} b
 * @property {boolean} same_content - Both known to hold the same content.
 * @property {ComparisonRow[]} rows
 * @property {SchemaDiff|null} schema_diff - Differences of the vector layers and
 *   their fields when both sides have them (own files and snapshots).
 */

/**
 * Differences of the vector layers of two sides, A changed into B.
 *
 * @typedef {object} SchemaDiff
 * @property {string[]} layers_only_a - Layers only A has, in A's order.
 * @property {string[]} layers_only_b - Layers only B has, in B's order.
 * @property {LayerDiff[]} layers - Layers of both sides, in A's order, also unchanged.
 */

/**
 * A vector layer of both sides: object counts and field differences.
 *
 * @typedef {object} LayerDiff
 * @property {string} name
 * @property {number|null} feature_count_a
 * @property {number|null} feature_count_b
 * @property {Array<{name: string, type: string}>} fields_added - Only in B.
 * @property {Array<{name: string, type: string}>} fields_removed - Only in A.
 * @property {Array<{name: string, type_a: string, type_b: string}>} fields_changed
 */

// Own data and snapshots (v0.2, step 9) --------------------------------------

/**
 * Parameters of `GET /projects/{project}/files`.
 *
 * @typedef {object} OwnFilesQuery
 * @property {string} [q] - Words that must all occur in the path.
 * @property {string} [state] - A file state (`ok`, `unrecognized`, `unreadable`,
 *   `missing`) or a change (`unsnapshotted`, `unchanged`, `changed`).
 * @property {number} [limit] - 1–200, default 50.
 * @property {string} [cursor] - `next_cursor` of the previous page.
 */

/**
 * A project's data folder as its last scan found it.
 *
 * @typedef {object} OwnFolder
 * @property {CopyPath} path - The folder (setting or `<project>/dane`).
 * @property {"default"|"setting"} source
 * @property {"ok"|"missing"|"unreadable"|"invalid"} state - `invalid`: refused by the
 *   rules (problem `own_folder_invalid`).
 * @property {number} files - Files present.
 * @property {number} size_bytes
 * @property {number} snapshots_bytes - Bytes of the snapshots in `.wersje/`.
 * @property {string|null} scanned_at - Null: not scanned yet (its state is now's).
 * @property {Issue[]} problems
 */

/**
 * The snapshot a file's change is measured against.
 *
 * @typedef {object} LastSnapshot
 * @property {string} label - E.g. `2026-10-18_471d37c0`.
 * @property {string} created_at
 */

/**
 * A file of a data folder, with its change since its last snapshot.
 *
 * @typedef {object} OwnFileItem
 * @property {string} file_id - 16 hex characters: the file in addresses (`own=`).
 * @property {string} path - Relative to the folder, `/` separated.
 * @property {string} ref - `file:<project>:<path>`; copy it, never compose it.
 * @property {string} kind - Kind of its format, as `PreviewKind`.
 * @property {string|null} format - GDAL driver; null: not read by GDAL.
 * @property {number} size_bytes
 * @property {string} modified_at
 * @property {"ok"|"unrecognized"|"unreadable"|"missing"} state
 * @property {"unsnapshotted"|"unchanged"|"changed"} change
 * @property {LastSnapshot|null} last_snapshot
 * @property {Location} location
 * @property {number} snapshots - Its snapshots in `.wersje/`.
 * @property {Geometry|null} outline - WGS84 polygon of its extent (with `footprint`).
 */

/**
 * Files of a data folder by path.
 *
 * @typedef {object} OwnFileList
 * @property {OwnFolder} folder
 * @property {OwnFileItem[]} items
 * @property {string|null} next_cursor
 */

/**
 * Content identity (decision 8): how it was computed and its SHA-256.
 *
 * @typedef {object} Content
 * @property {"bytes"|"fileset"|"sqlite"} method
 * @property {string} sha256
 */

/**
 * An observed state of a file (its history, without content).
 *
 * @typedef {object} Observation
 * @property {string} observed_at
 * @property {number} size_bytes
 * @property {string} modified_at
 * @property {string|null} content_sha256
 * @property {number|null} feature_count
 */

/**
 * A snapshot of a file in `.wersje/` (`archiwista-snapshot/1`).
 *
 * @typedef {object} SnapshotItem
 * @property {string} label - Its directory, `<RRRR-MM-DD>_<sha8>`.
 * @property {string} ref - `snapshot:<project>:<label>:<path>`.
 * @property {string|null} created_at
 * @property {{id: string, kind: string, name: string|null, session: string|null}|null}
 *   author
 * @property {string|null} note - The person's note.
 * @property {number} size_bytes
 * @property {Content|null} content
 * @property {number|null} feature_count
 * @property {{crs: string|null, bbox: number[], wgs84: number[]|null}|null} extent -
 *   Of the copy: in its CRS and as a WGS84 box (west, south, east, north).
 * @property {"ok"|"invalid"|"modified"} state - `invalid`: no valid `migawka.json`;
 *   `modified`: its files differ from the document.
 * @property {CopyPath} paths - The snapshot directory.
 */

/**
 * A vector layer of an own file as GDAL read it.
 *
 * @typedef {object} OwnLayer
 * @property {string} name
 * @property {string|null} geometry_type - OGR's name; null: a table without geometry.
 * @property {number|null} feature_count
 * @property {Array<{name: string, type: string}>} fields
 * @property {string|null} crs
 * @property {number[]|null} bbox - In `crs`.
 */

/**
 * Everything known of an own file (`GET /projects/{project}/files/{file_id}`).
 *
 * @typedef {object} OwnFileCard
 * @property {string} file_id
 * @property {string} path
 * @property {string} ref
 * @property {string} kind
 * @property {string|null} format
 * @property {number} size_bytes
 * @property {string} modified_at
 * @property {"ok"|"unrecognized"|"unreadable"|"missing"} state
 * @property {"unsnapshotted"|"unchanged"|"changed"} change
 * @property {LastSnapshot|null} last_snapshot
 * @property {Location} location
 * @property {OwnLayer[]} layers
 * @property {{width: number, height: number, bands: number, dtype: string,
 *   nodata: number|null, pixel_size: number[]|null, georeferenced: boolean}|null} raster
 * @property {string|null} crs - `EPSG:<code>` or WKT.
 * @property {{bbox: number[], wgs84: Geometry|null}|null} extent - `bbox` in `crs`.
 * @property {Content|null} content
 * @property {Observation[]} history - Observed states, newest first (≤ 200).
 * @property {SnapshotItem[]} snapshots - Newest first.
 * @property {PreviewInfo|null} preview - Null without render processes.
 * @property {CopyPath} paths - The main file.
 * @property {Issue[]} problems
 */

/**
 * What a snapshot of a file would do now (`GET …/snapshot-plan`); nothing is written.
 *
 * @typedef {object} SnapshotPlan
 * @property {string} file - The working file, relative to the data folder.
 * @property {number} size_bytes - Bytes to copy (the set, a SQLite `-wal` too).
 * @property {CopyPath} destination - `.wersje/<file>/`.
 * @property {"sqlite_backup"|"files"} copy_method
 * @property {"sqlite"|"fileset"|"bytes"} content_method
 * @property {LastSnapshot|null} unchanged_since - The last snapshot holds the content.
 * @property {{code: "folder_invalid"|"read_only_folder"|"insufficient_space"
 *   |"file_missing", message: string}|null} blocked - Why it would be refused now.
 * @property {number|null} free_bytes - Free bytes where it goes; null: out of reach.
 * @property {Array<{code: string, message: string}>} warnings - E.g.
 *   `editing_detected`.
 */

// The source and producers' commands (v0.3) ------------------------------------

/**
 * The kept report `GET /availability` returns, and how to read its rows.
 *
 * @typedef {object} AvailabilityQuery
 * @property {string} area_id
 * @property {string} product - A product of the producer's `availability` (`GET /sources`).
 * @property {string} [producer] - Default `kartograf`.
 * @property {string} [store] - A configured store: each variant gets its store badge.
 * @property {string} [horizontal] - Only variants of this sheet system (`PL-1992`).
 * @property {string} [resolution]
 * @property {string} [vertical_crs]
 */

/**
 * Body of `POST /availability`.
 *
 * @typedef {AvailabilityQuery & {force?: boolean}} AvailabilityRequest - `force`: ask
 *   the source even when a report younger than seven days is kept.
 */

/**
 * A coverage label as structure (SPEC 6.4); `label` beside it is its text.
 *
 * @typedef {object} CoverageInfo
 * @property {"full"|"full_campaigns"|"partial"|"no_data"} kind
 * @property {number} campaigns - Distinct campaigns of the sheets a download takes.
 * @property {number|null} full_share - Land in full sheets over the area's land, 0-1.
 * @property {number|null} percent - Rounded down, at most 99 if partial.
 * @property {boolean} below_one - A share above zero below 1% (`<1%`).
 * @property {number} partial_sheets
 * @property {number} missing_sheets
 */

/**
 * How much of a variant's set a store holds (the store badge).
 *
 * @typedef {object} StoreBadge
 * @property {string} store
 * @property {"all"|"some"|"none"} state
 * @property {number} units - Units with a version of the set.
 * @property {number} of - The set's units.
 * @property {string} label - „pobrane”, „pobrane 5/12”, „niepobrane”.
 */

/**
 * One set of the source in each of its formats (A-ADR-017).
 *
 * @typedef {object} AvailabilityVariant
 * @property {string} horizontal - Sheet system or horizontal CRS (`PL-2000`).
 * @property {string|null} resolution - Null for point clouds.
 * @property {string} vertical_crs
 * @property {string[]} campaigns
 * @property {string[]} formats - Its badges, in the report's order.
 * @property {string|null} default_format - ASC, then TIFF; null: the plan asks for a
 *   choice.
 * @property {number|null} size_bytes - Of the default format; null when unknown.
 * @property {string} label - The coverage label for people.
 * @property {CoverageInfo} coverage
 * @property {StoreBadge|null} local - Null without a store in the request.
 * @property {Object<string, string[]>} commands - The producer's command lines that
 *   download the set, by format (`POST /commands/parse` reads each).
 */

/**
 * One year of one country: its best variant first.
 *
 * @typedef {object} AvailabilityRow
 * @property {string} country
 * @property {number|null} year - Null for CZ.
 * @property {string} label - The first variant's label, else „brak danych”.
 * @property {CoverageInfo} coverage
 * @property {StoreBadge|null} local - The first variant's badge.
 * @property {number} other_variants - The chip „+N wariantów”.
 * @property {AvailabilityVariant[]} variants - Empty for `no_data`.
 */

/**
 * The last report of what the source has for an area and a product.
 *
 * @typedef {object} AvailabilityInfo
 * @property {{id: string, name: string|null, area_km2: number|null, countries: string[]}} area
 * @property {string} producer
 * @property {string} product
 * @property {string} checked_at - When the source was asked.
 * @property {string|null} job_id - The `availability` job that asked.
 * @property {string|null} store - The store of the badges.
 * @property {{horizontal: string|null, resolution: string|null, vertical_crs:
 *   string|null}} variant - The dimensions of the request.
 * @property {AvailabilityRow[]} rows
 * @property {{producer: string, schema: string, checked_at: string, ok: boolean,
 *   failed: Array<{part: string, detail: string, kind: string}>,
 *   notices: Array<{level: string, code: string, message: string}>}} report - The
 *   producer's report (also its `areas` and `combinations`).
 */

/**
 * A call of a producer's command (`POST /commands/parse`).
 *
 * @typedef {object} CommandCall
 * @property {string} producer
 * @property {string} command - Of the producer's catalog (`GET /commands`).
 * @property {Object<string, *>} options - In the JSON form of the catalog.
 * @property {Object<string, *>} run - What a line gives beside the options (`root`…).
 */

/**
 * Body of `POST /commands/validate`: a call checked without the network.
 *
 * @typedef {object} ValidateRequest
 * @property {string} producer
 * @property {string} command
 * @property {Object<string, *>} options
 * @property {string} [store] - The configured store whose directory of the producer a
 *   command that works on a store is checked with.
 */

/**
 * One call of a job: a command of the producer's catalog and its options.
 *
 * @typedef {object} CallRequest
 * @property {string} command
 * @property {Object<string, *>} options
 */

/**
 * Body of `POST /jobs`: a job of a producer's calls on a configured store, all
 * the lines of a row in one job (ADR-044).
 *
 * @typedef {object} JobRequest
 * @property {"check"|"download"} kind
 * @property {string} producer
 * @property {string} store - Its directory of the producer is the store root.
 * @property {CallRequest[]} calls - 1 to 1000, run one after the other; a refusal of
 *   one names its place as `details.call`.
 * @property {string} [plan_job] - `download` only: the `check` job of the same calls
 *   whose plans it runs.
 */

/**
 * One position of a plan.
 *
 * @typedef {object} PlanEntry
 * @property {string} path - Below the store root.
 * @property {string} unit - The producer's unit (a sheet, a tile, a station).
 * @property {"current"|"newer"|"missing"|"unverifiable"|"check_failed"} status - A run
 *   downloads `newer` and `missing`.
 * @property {string|null} local_label
 * @property {string|null} available_label
 * @property {number|null} size_bytes - Null when the producer does not tell it.
 * @property {string|null} error - The producer's text of a failed check.
 * @property {string|null} conflict - Why a run would refuse to write it
 *   (`nested_store`, `not_empty`).
 */

/**
 * The plan of one call of a `check` job.
 *
 * @typedef {object} CallPlan
 * @property {number} call - Its place in the job's `calls`, from 0.
 * @property {string} command
 * @property {Object<string, *>} options - As the producer read them.
 * @property {string} line - The producer's command line of the run, with the root.
 * @property {string} schema
 * @property {string} checked_at
 * @property {boolean} ok - No position is `check_failed`.
 * @property {Object<string, number>} counts - Positions of each status.
 * @property {number} todo - Positions a run downloads.
 * @property {number|null} size_bytes - Of the positions to download as far as the
 *   producer tells; null when it tells none of them, never 0 for unknown.
 * @property {boolean} size_complete - Every position to download has its size.
 * @property {PlanEntry[]} entries
 * @property {Array<{level: string, code: string, message: string}>} notices
 */

/**
 * The plans a `check` job kept (`GET /jobs/{job}/plan`): their totals and the
 * plan of each call planned (a call whose check failed has none).
 *
 * @typedef {object} ActionPlanInfo
 * @property {string} job_id
 * @property {string} store
 * @property {string} producer
 * @property {string} root - The store root the producer planned for.
 * @property {string} checked_at - Of the oldest plan.
 * @property {boolean} ok - Every call planned and no position `check_failed`.
 * @property {Object<string, number>} counts - Positions of each status in all plans.
 * @property {number} positions
 * @property {number} todo - Positions the runs download.
 * @property {number|null} size_bytes - Of the positions to download as far as the
 *   producer tells; null when it tells none of them, never 0 for unknown.
 * @property {boolean} size_complete - Every position to download has its size.
 * @property {CallPlan[]} calls - In the order of the job's calls.
 */

export {};
