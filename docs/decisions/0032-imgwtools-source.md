# ADR 0032: The IMGWTools source: one adapter, the extra, read first

**Date:** 2026-10-25
**Status:** Accepted. Supplements A-ADR-019 and A-ADR-024. Decided by the plan
`docs/plans/2026-10-25-archiwista-next.md` (Part 2, steps I1 and I2), whose approval is
delegated; the author may still amend it (D8).

**Context:** A-ADR-019 gave Archiwista two producers behind one source interface, and
A-ADR-024 made Kartograf required and IMGWTools an optional plugin, both before IMGWTools
had a store contract. IMGWTools 3.0.0 (untagged; its branch `feature/data-output`, its
ADR-007) has one now: the marker `imgw-store.json` (`imgw-store/1`), the sidecar
`imgw-meta/1`, the series index `imgw-series/1`, the project manifest `imgw-project/1` and a
read API (`store_info`, `iter_store`, `read_meta`, `open_project`, `get_project_status`).
One package and one store root serve two providers, IMGW-PIB and ČHMÚ (`provider`
`IMGW-PIB` and `CHMI`); the dataset key (`pl.imgw.hydro_daily`, `cz.chmi.hydro_daily`) tells
their files apart. The plan builds the read side first, on its own branch, and ships it with
0.5.0 (D4). Options: (a) one plugin for both providers; (b) one plugin per provider; (c)
IMGWTools as a required dependency; (d) reading the files of the store without the package;
(e) the actions of IMGWTools (check, synchronise, build, export) together with the read
side.

**Decisions:**

1. **One plugin for both providers (a).** The entry point is
   `imgw = "archiwista.adapter.imgw:load"`. `archiwista.adapter.imgw` declares
   `PRODUCER = "imgw"`, `PACKAGE = "imgwtools"`, `SUPPORTED_VERSIONS = ">=3.0.0,<4"` and the
   four `SCHEMAS` it reads; its factory compares the installed IMGWTools with the range
   before it imports the package, so a missing or unsupported one is a state of this source
   (`not_installed`, `incompatible`) and nothing else stops. The segment of an entry is its
   dataset, so the files of the two providers never mix; a slot is the directory that holds
   the versions of one file. (b) is rejected: one package, one store root and one marker
   would be probed by two plugins, and the settings name one directory per producer.
2. **The dependency is the extra `archiwista[imgw]`.** It is `imgwtools[store]` pinned by
   commit (REL-5.3) until the tag `v3.0.0`; `[store]` brings `pyarrow` for the Parquet
   series, which the adapter never imports. One lock holds both configurations
   (A-ADR-024, item 5) and CI runs the offline suite once with the extra, in the gate, and
   once without it (A-ADR-024, item 6). (c) stays rejected by A-ADR-024; (d) by A-ADR-014:
   the knowledge of the layout stays with the producer.
3. **A missing source is a state.** `GET /sources` and `archiwista doctor` list `imgw` whether
   or not IMGWTools is installed. Without it the state is `not_installed` and the fix is
   `pip install "archiwista[imgw]"`; for a source that no store uses, `doctor` reports a
   warning and its exit status stays 0. Kartograf and everything else are unaffected.
4. **Read first (e is rejected).** The adapter implements the source interface and no
   optional capability: it probes a directory, scans the entries of `iter_store`, reads
   the metadata of a file again, places a file by its country and reads a project and its
   status. It writes nothing and uses no network; the store stays read-only for Archiwista.
   Archives, series, station catalogs and PMAXTP cells are versions; what the producer cannot
   read is a problem with the producer's own problem code, never a state of the source;
   the observation register of a slot (a source republished the same content) is
   publication history and never a version, a link or a count. The actions of IMGWTools
   follow on the action layer of v0.3 (plan, Part 3), in v0.5.
5. **The marker is judged in the adapter, by file name and schema** (DEV-19.12, DEV-19.13).
   An empty root, or one holding only the server's `api_keys.json`, is `available` (the first
   write creates the marker); a root with `archives`, `series`, `stations` or `pmaxtp` and
   no marker is `incompatible` with the reason `no_marker` and the hint
   `imgw store init --root <path>`; another schema or an unusable marker is
   `unsupported_marker`; `kartograf-store.json` is `foreign_store`; any other directory is
   `not_a_store`. `SourceState` carries the `reason` and the `hint`. The contract tests pin
   every verdict to what `init_store`, `open_store` and `iter_store` of IMGWTools do with the
   same directory, so the judgement cannot drift.
6. **A settings change looks for nested stores two levels down.** DEV-19.14 wants the
   ancestors and the existing descendants of a store root searched for markers. The producers'
   writers walk the whole tree below a root before they write; a settings change that did the
   same would list the 50,000 slots of a large store, on a share, at every new or moved
   directory. `check_nesting` looks in the ancestors of the real path, and in the directories
   up to two levels below it (the products and segments of Kartograf, the trees and datasets
   of IMGWTools: a few dozen), never through a link, and only around a new or a moved
   directory, so a share that is not connected does not block other edits. A store put deeper
   is found by the producer's writer when it writes. Rejected: the full walk, and the ancestors
   alone (a store below the directory is the nesting that a later write would refuse).

**Consequences:** A default installation shows `imgw` as `not_installed` in the sources list
and as a warning of `doctor`. The tests that assumed Kartograf is the only source change;
the tests of the adapter import IMGWTools and are not collected without it. The pinned
commit is not on GitHub yet, so the lock resolves it only where the uv git database of
IMGWTools holds it, and CI cannot be green before IMGWTools is pushed (plan, risks); the
release pull request replaces the commit with the tag. IMGWTools lacks four things the adapter
works around without changing the producer, to be requested there (DEV-17.5): a machine code
in `StoreInfo`, the `producer` and `producer_version` of a sidecar in `Meta`, a list of
known versions for `iter_store` (every scan reads every sidecar) and one rule for a marker
without `created_by` (the reader refuses it, `open_store` accepts it). A store takes an IMGW
directory beside or instead of its Kartograf one (the settings step of the same plan,
`StoreConfig.imgw`): the scan indexes its files as versions of their slots, without a
current version; a source that is not available has its directory skipped and its entry
kept (SPEC 5.8); and a directory that lies in a store of any producer or holds one is refused
by the marker file names at its own field (DEV-19.14), looking two levels down because the
producer's writer, which looks at the whole tree, is not run by a settings change. The
current version, the index of IMGW slots, the stations and the series coverage come after it.

**Errata:** none.
