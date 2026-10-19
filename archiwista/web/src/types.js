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
 * @property {"local_owner"|"user"|"agent"} kind - How: the owner, a signed-in person
 *   (team mode) or an agent for `actor`.
 * @property {string} label - Label of the session, recorded with its jobs and permission
 *   changes.
 * @property {string} expires_at - End of the session unless used again: each request
 *   extends it by 24 h; an agent's session ends 12 h after its start at the latest.
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
 * An error, as `application/problem+json` (RFC 9457), with the members some
 * codes add.
 *
 * @typedef {object} Problem
 * @property {string} type - `/api/v1/problems/<code with hyphens>`.
 * @property {string} title - Polish title of the code.
 * @property {number} status - HTTP status; `0` when the server did not answer.
 * @property {string} detail - Polish description: what and how to fix.
 * @property {string} code - Stable machine code: validation_error, not_found,
 *   method_not_allowed, session_required, csrf_rejected, permission_denied,
 *   path_outside_root, conflict, offline_mode, store_unavailable, source_unavailable,
 *   source_incompatible, kartograf_error, area_too_large, area_unreadable,
 *   area_too_complex, internal_error…; the client adds `network_error` and
 *   `http_error`.
 * @property {Array<{code: string, field: string, message: string}>} [problems] - Invalid
 *   settings, field by field (`field` like `stores[0].kartograf`).
 * @property {Array<{field: string, type: string, message: string}>} [errors] - Invalid
 *   request data.
 * @property {{id: string, state: string, package_version: string|null,
 *   supported_versions: string|null, requirement: string}} [source] - An unavailable
 *   producer plugin and the pip requirement fixing it.
 * @property {{id: string, kind: string, state: string}} [job] - The running job of a
 *   `409 conflict`.
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
 * Every registered producer plugin, ordered by producer.
 *
 * @typedef {object} SourceList
 * @property {SourceInfo[]} items
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
 * Filters shared by `GET /slots` and `GET /map/footprints` (unknown ones answer 422).
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
 *   query; null on the last page. A cursor of other filters is rejected (422).
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
 * A sheet of a map sheet grid with its outline.
 *
 * @typedef {object} Sheet
 * @property {string} sheet - Sheet code (godło).
 * @property {Geometry} geometry - GeoJSON polygon in WGS84.
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
 * A discovered project the session's principal sees.
 *
 * @typedef {object} ProjectItem
 * @property {string} project - Project id: /projects/{project}.
 * @property {string} name
 * @property {string} producer
 * @property {string|null} store - Configured store the manifest names; null when none
 *   matches.
 * @property {string|null} status - Producer's status when the manifest was read: `ok`,
 *   `not_downloaded`, `missing` or `corrupt`; null when not checked.
 * @property {string|null} problem - Producer's message for an invalid manifest.
 * @property {string} scanned_at
 * @property {number} tasks
 * @property {number} pins
 * @property {number} missing_pins - Pins missing from the store or other.
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
 * A task of a project with its existing command and options.
 *
 * @typedef {object} ProjectTask
 * @property {string} task
 * @property {string} command - Producer command as in the manifest.
 * @property {Object<string, *>} options - Options as in the manifest.
 * @property {string|null} status
 */

/**
 * A version a project task pinned (older versions too).
 *
 * @typedef {object} ProjectPin
 * @property {string|null} task
 * @property {string} version - Pinned version path.
 * @property {string|null} sha256
 * @property {PinState} state
 * @property {string|null} slot
 * @property {string|null} label
 * @property {number|null} size_bytes
 * @property {boolean} is_current
 */

/**
 * A project: tasks with their commands, pinned versions and problems.
 *
 * @typedef {object} ProjectCard
 * @property {boolean} stale
 * @property {StaleStore[]} stale_stores
 * @property {string} project - Project id: /projects/{project}.
 * @property {string} name
 * @property {string} producer
 * @property {string|null} store - Configured store the manifest names; null when none
 *   matches.
 * @property {string|null} status - Producer's status when the manifest was read; null:
 *   not checked.
 * @property {string|null} problem - Producer's message for an invalid manifest.
 * @property {string} scanned_at
 * @property {number} missing_pins - Pins missing from the store or other.
 * @property {ProjectTask[]} tasks - Tasks in manifest order.
 * @property {ProjectPin[]} pins - Pinned versions, older ones too.
 * @property {Issue[]} problems - Invalid manifest, unknown store, missing or other
 *   pinned files.
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
 * The producer's check of a project now (no network, no hashing).
 *
 * @typedef {object} ProjectStatus
 * @property {string} project
 * @property {string} producer
 * @property {string|null} status - The worst task status.
 * @property {string} checked_at - When the producer checked: now, or the last scan when
 *   stale.
 * @property {boolean} stale - True: the store is unavailable, the scan's check is
 *   shown.
 * @property {string|null} stale_reason
 * @property {TaskStatus[]} tasks
 */

// Settings (9a) --------------------------------------------------------------

/**
 * A configured store: a short id and the producer's directory.
 *
 * @typedef {object} StoreSettings
 * @property {string} id - Short id in the API: lowercase letters, digits, '_', '-' (≤
 *   32).
 * @property {string} name
 * @property {string} kartograf - Kartograf's --output directory (the data/ directory
 *   itself).
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
 * @property {"xyz"|"wms"} [kind] - `xyz` tiles or `wms`.
 * @property {string} url - Tile template with {z}/{x}/{y}, or a WMS address.
 * @property {string} [attribution]
 * @property {boolean} [grayscale]
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
 * @property {BasemapSettings[]} [basemaps] - Grey BKG TopPlusOpen when omitted.
 * @property {boolean} [store_write_for_all] - Everyone may write to stores, not only
 *   `store_writer` (v0.3).
 * @property {"public"|"private"} [default_project_visibility] - Visibility of a project
 *   without its own access entry.
 * @property {number} [preview_cache_limit_gb] - Preview cache limit in GB (1024³ bytes),
 *   1–10 000; the least recently used previews go first.
 */

// Background jobs (9b) -------------------------------------------------------

/**
 * Why a job ended without success.
 *
 * @typedef {object} JobFailure
 * @property {string} code - store_unavailable, source_unavailable, kartograf_error,
 *   offline_mode, worker_crashed, interrupted, cancelled…
 * @property {string} detail - Polish description.
 */

/**
 * A background job: `202` of POST …/scan, …/footprints, …/link-check, `GET
 * /jobs/{job}` and the items of `GET /jobs`.
 *
 * @typedef {object} JobDetail
 * @property {string} id
 * @property {"scan"|"footprints"|"link_check"|"preview"} kind
 * @property {"queued"|"running"|"succeeded"|"failed"|"interrupted"|"cancelled"} state
 * @property {string} actor - Who started it.
 * @property {"local_owner"|"user"|"agent"|"scheduler"} actor_kind - How: the owner, an
 *   account, an agent for `actor`, or the scheduler.
 * @property {string|null} session - Label of the session it was started in.
 * @property {string} store
 * @property {Object<string, *>} params - `mode`/`segment` of a scan, `slot` of a link
 *   check.
 * @property {string} created_at
 * @property {string|null} started_at
 * @property {string|null} finished_at
 * @property {Object<string, *>|null} progress - Data of the last progress event.
 * @property {Object<string, *>|null} result - Summary of a succeeded job.
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
 * @property {number} [limit] - 1–200, default 50.
 * @property {string} [cursor]
 */

/**
 * Body of `POST /stores/{store}/scan`.
 *
 * @typedef {object} ScanRequest
 * @property {"incremental"|"full"} [mode] - Default `incremental`.
 * @property {string} [segment] - Only this segment.
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
 * @property {Object<string, *>|null} schema_diff - Layers and fields of own data.
 */

export {};
