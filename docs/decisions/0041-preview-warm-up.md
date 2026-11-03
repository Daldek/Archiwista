# ADR-041: The warm-up of previews: the first look, a pool of its own, the room of the cache

**Date:** 2026-10-26
**Status:** proposed (done on the topic branch `feature/kartograf-data-output`, step A9 of the plan `docs/plans/2026-10-25-archiwista-next.md`, whose approval is delegated; accepted when the author approves and merges the branch)

**Context:** v0.3 prepares previews of current versions ahead (SPEC 5.7, user decision 2026-10-19; SPEC 13 v0.3 criterion 8): a store on an HDD or a share is slow at its first read, while the local preview cache is fast. The job must not delay people's previews, must stay within the cache limit and never evict a preview used lately, must stop with the reason and the number of versions skipped when the room runs out, uses no network, reads the stores only and keeps the visibility of own data (A-ADR-029). The render pool (`RenderPool`) lives in the server process; every job runs in a worker process (A-ADR-007).

**Options:**
- What is prepared:
  - A) Every tile of a file. Rejected: SPEC 5.7 says "not all tiles", and the cache would hold few files.
  - B) What a person's first look asks for: the preview pane's thumbnail (512 px, the default style) and the map's tiles at the file's smallest zoom, and the probe.
- Local COGs (`needs_cog`, a consistent copy of a working GeoPackage):
  - C) Build them too. Rejected: a COG costs as much as a converted copy of its file and minutes of a build process; a store's warm-up would spend the room on a few hundred COGs instead of the thumbnails of all files. The interface builds one at the first view (`auto_build`).
  - D) Never: such a file gets its thumbnail only and counts as `needs_build`.
- The render processes:
  - E) A background lane in the server's pool. Rejected: the job's worker cannot reach it, and a warm-up would then run in the server process.
  - F) A pool of its own in the worker: one render process, the worker and it at the lowest CPU priority (`nice` 19); the cache is shared.
- "Used lately":
  - G) Since the job started. Rejected: an object used yesterday could go.
  - H) Within the last seven days (`RECENT_S`), from the cache's own use times.

**Decision:** B, D, F and H.

1. **Job** (`preview_warm`, `PROTOCOL_VERSION` 9). Parameters `WARM_FILTERS`: `store`, `product`, `segment`, `project`, `area_id` and `since` (the scheduler's warm-up after a scan), each `None` when not given; no store of the job (`store` is `null`), one warm-up at a time (`exclusive`), a request of the filters of a waiting one joins it. The worker selects the present current versions the filters admit as the catalog's current rows do (`IndexQueries.warm_selection`); with `project`, those the project pins and the working files of its own data (none with `product`, `segment` or `since`).
2. **The first look** (`previews.service.first_look`) is the rule of the interface: nothing for a file that shows nothing; nothing for one whose thumbnail waits for its build past the auto-build limits; the thumbnail only for a vector (its map shows features) and for a file whose tiles wait for a build.
3. **The cache.** Whether an object holds the first look is read without counting a use (`PreviewCache.peek`, `has`), so a warm-up never makes old objects look recent; a version with a `sha256` the cache holds whole is not read from its store. Before rendering a file, `PreviewCache.room(used_before=now - RECENT_S)` says how much puts may add without evicting an object used since: what stays below the limit, or what the objects used before can make room for (eviction goes down to 90% of the limit, least recently used first). Below `RESERVE_BYTES` (4 MiB, a file's first look at most) the job stops: the files not reached are `skipped`, `stopped` is `cache_full`, a warning notice says so.
4. **Outcome.** A file that fails fails alone (`failed`, the first 100 named in `failures`); a warm-up with failures or skipped files ends `partial`. The summary also has `warmed`, `cached`, `needs_build`, `room_bytes` and `seconds`.
5. **Requests** (commit 2). `POST /previews/warm` (body `WarmRequest`: `store`, `product`, `segment`, `project`, `area_id`, each optional) and `archiwista preview-warm` (a command of its own: `preview` takes a positional ref, as `project KEY` stands beside `project-download`) call `services.warm.start`, which refuses before a job exists a store that is not configured, a project the principal does not see (as an unknown one) and an area the index does not keep, each `404`. Any session may warm: the job uses no network, only reads the stores and writes the preview cache, as a `preview` build does. A job with `project` is that project's: the supervisor shows it only to those who see the project (its scope of `params.project`); a warm-up without `project` never selects own data.
6. **After a scan** (commit 2). The setting `preview_warm_after_scan` (off by default; `AppSettings`, `PUT /settings`): each tick of the `ScanScheduler`, a store with no job of its index waiting or running gets, for its newest succeeded scan that wrote versions (`versions_written`), one `preview_warm` of the scheduler with `store` and `since` the scan's `started_at`. The scans followed are kept in memory (the newest scan id per store), so a restarted server follows each store's newest scan once more; that warm-up finds its work in the cache.

**Consequences:**
- Criterion 8 holds by construction (the server reads a warmed thumbnail from the cache without opening the store); its time on the reference computer is measured in A14.
- The warm-up's own objects are used when they are written, so they count as recent for seven days; a full cache of previews used this week takes no warm-up (raise `preview_cache_limit_gb`).
- A file whose map needs a local COG is warmed only half-way; the interface's auto-build still runs at its first view.
- A9 commit 2 adds `archiwista preview-warm`, `POST /previews/warm` and the administrator's setting that starts a warm-up after a scan; the interface has no control for either yet (the setting is kept when the settings form is saved).
- A scan writes only new and changed versions (`versions_written`), and `since` admits only those first indexed since the scan started (a known version whose sidecar changed keeps its `indexed_at`), so the warm-up after a scan prepares what is new; a scan that only changed sidecars starts a warm-up that selects nothing.
