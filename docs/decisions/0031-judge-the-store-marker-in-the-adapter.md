# ADR-031: Judge the store marker in the adapter, and refuse a store without one

**Date:** 2026-10-25
**Status:** proposed (done on the topic branch `feature/kartograf-data-output`; decisions D1 and D2 of the plan `docs/plans/2026-10-25-archiwista-next.md` were accepted by delegated approval; accepted when the author approves and merges the branch)

**Context:** The data-output convention (Nogat DEV §19, ECO-051; Kartograf ADR-054) makes a
store a root directory with a marker, `kartograf-store.json` of the schema
`kartograf-store/1` (`schema`, `tool`, `created_at`, `producer_version`). The first write into
a new or empty root creates it; `kartograf store init` (the public `kartograf.init_store`)
marks an existing store after verifying its layout; a root that has the layout of a store but
no marker is `store_unavailable` (`no_marker`) for a writer; a store never holds another store,
whichever tool wrote it (DEV-19.12 to DEV-19.14). IMGWTools keeps the same convention with
`imgw-store.json`. Archiwista only reads, so the rule falls to its probe of a configured
directory (`probe`, SPEC 5.3), which until now looked at the segments only: it said `incompatible`
when none was a segment of Kartograf and `available` otherwise, the marker unseen. Kartograf's
public API has no function that tells a marked, an unmarked and a foreign directory apart
(`describe_store` lists segments; the request `store_state(root)` is in the plan).

**Options:**
- A) Strict (D1): a directory with the layout and no marker is unavailable until the
  producer's `store init` has run; Archiwista shows the command and never runs it (D2).
- B) Lenient: index such a directory and warn. Rejected: a store with no marker is exactly the
  store the producer's own writer refuses, so an action of v0.3 (download into it) would fail
  where the reading works, and a directory that is not a store at all would be indexed as one.
- C) Strict, and Archiwista writes the marker through `kartograf.init_store` in a job
  (an action "Utwórz znacznik" with `store.write`). Not now: the store is read-only for
  Archiwista (ADR-003); the author may take it later (D2).
- D) Judge the marker in the generic layer for every producer. Rejected: the marker is a
  producer's format (ADR-014); each adapter judges its own, and a state travels as the
  producer-neutral `SourceState` (`status`, `detail`, `reason`, `hint`).

**Decision:** A, judged in the Kartograf adapter (`adapter/kartograf/marker.py`) by file name
and schema, after `list_segments`:

| Directory | `status`, `reason` |
|---|---|
| cannot be listed, or its marker cannot be read | `error` (the system's message) |
| `imgw-store.json` in the root | `incompatible`, `foreign_store` |
| `kartograf-store.json` of the schema `kartograf-store/1` | `available` |
| `kartograf-store.json` of another schema, not JSON, not an object or without `schema` | `incompatible`, `unsupported_marker`; the text names both schemas where it can |
| no marker, no segment (an empty directory: a new store) | `available` |
| no marker, segments, none known to Kartograf (the parent of a store) | `incompatible`, `not_a_store`; the text asks for the directory that holds `kartograf-store.json` |
| no marker, a file below a known segment (`.incoming` does not count) | `incompatible`, `no_marker`; hint `run once: kartograf store init --root <path>` |
| no marker, known segments and no file below them | `available` (no layout yet) |

1. **The marker decides.** A valid marker makes the directory a store whatever the segments
   are, and the marker of another tool makes it foreign even when it has segments. Without a
   marker the segments decide, and a first file below the known segments is looked for only
   then, so a probe of a marked store costs two `stat` calls and one small read more.
2. **The layout is Kartograf's.** A file below a known segment outside the staging directory
   `.incoming` is what Kartograf's own writer takes for the layout of a store (its `init_store`
   verifies such a root before it marks it); directories without a file, and what a writer is
   still staging, are a store that does not exist yet.
3. **Nothing of another tool is imported.** The file names are `kartograf-store.json` and
   `imgw-store.json` (DEV-19.12); the judgement is a copy of producer knowledge, kept until
   Kartograf offers `store_state(root)` (plan, "Requests"), and a contract test pins it to the
   producer's own writers: `kartograf.testing.build_fixture_store` builds the stores,
   `kartograf.init_store` heals one, and Kartograf's own refusals (`InvalidLayoutError`,
   `ConflictError` `nested_store`) agree with the states. Archiwista does not check the
   ancestors and descendants of a root for another store: that is the writer's rule.
4. **The reason and the fix travel.** `SourceUnavailableError`, `SettingsProblem` and the
   doctor carry the `reason` and the `hint` of a probe (`SourceState`): a scan job
   fails with `store_unavailable` and `details.reason` `no_marker` with the hint, `PUT
   /settings` answers `400` with the same reason and hint at `stores[n].kartograf`, and
   `archiwista doctor` prints the command as the fix. The texts are catalog entries in both
   languages (`source.no_marker`, `source.foreign_store`, `source.unsupported_marker`,
   `source.invalid_marker`, `source.kartograf_not_store`, `fix.store_init`).
5. **The generated stores are marked.** `tests/fixtures/store_marker.mark_store(root)` calls
   `kartograf.init_store` on the empty root, and `make_store`, `make_preview_store` and
   `make_layer_store` call it before they write a file. `make_store.py` stays the source of
   scale (50,000 slots, every family, the deliberately broken cases), which `kartograf.testing`
   does not offer.

**Consequences:**
- **Breaking.** A store written by an earlier Kartograf has no marker, so every configured
  store of an existing installation is `unavailable` at the first start on the new pin, until
  `kartograf store init --root <path>` has run once for it (D9). That command verifies the layout
  first and refuses a store with stray entries (`invalid_layout`, the list in
  `details.problems`), which the author moves out. That is for the live-test store; the large
  synthetic stores of the `perf` and `smb` runs have deliberate defects that `init` refuses,
  so they are generated again (the generator marks first).
- A directory that is not a store and has no segments (a new mount point) is `available` and
  empty, as before; a directory with segments none of which is Kartograf's is `not_a_store`
  with a text that names the marker instead of `--output`.
- The IMGW source (step I1) adds the judgement of `imgw-store.json` in its own adapter;
  `OTHER_MARKERS` of the Kartograf adapter lists it by name for `foreign_store`.
- A change of the marker's name or schema in Kartograf, or of what it takes for a layout,
  fails a contract test when the pin moves, instead of a person's store being mis-judged.
