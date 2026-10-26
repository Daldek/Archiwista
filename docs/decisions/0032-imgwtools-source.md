# ADR 0032: The IMGWTools source: one adapter, the extra, read first

**Date:** 2026-10-25
**Status:** Accepted. Supplements A-ADR-019 and A-ADR-024. Decided by the plan
`docs/plans/2026-10-25-archiwista-next.md` (Part 2, steps I1 to I3), whose approval is
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
4. **Read first (e is rejected).** The adapter implements the source interface and two optional
   capabilities (decisions 7 and 8): it probes a directory, scans the entries of `iter_store`, reads
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
   `unsupported_marker`, decided by the codes of `StoreInfo.problem_codes`
   (`unsupported_store`, `invalid_marker`); `kartograf-store.json` is `foreign_store`; any
   other directory is `not_a_store`. The producer gives a layout without its marker and a
   directory that is no store the same code (`missing_marker`), so the names in the
   directory tell those apart. `SourceState` carries the `reason` and the `hint`. The
   contract tests pin every verdict to the codes of `store_info` and to what `init_store`
   and `open_store` of IMGWTools do with the same directory, so the judgement cannot drift.
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
7. **A slot has the producer's key, a segment is a dataset, and history stays history**
   (plan I3, `SCHEMA_VERSION` 7). Beside what Kartograf's layout gives, the index keeps the
   producer's own name of a slot (`slots.slot_key`, opaque to the index: for IMGWTools
   `archive:pl.imgw.hydro_daily:2024/codz_2024.zip`, `series:<dataset>`,
   `catalog:<provider prefix>.stations`), the provider of a version (`versions.provider`)
   and the observation register of an archive slot (table `observations`). `SourceEntry`
   carries `slot_key`, `slot_name` (a name for people where the directory's name is none:
   the file of an archive, the key of a catalog) and `observation`. IMGWTools has no
   segments to scan: `iter_store` has no scope below the root, so a pass per dataset would
   read the whole store once per dataset. Its entries still name their dataset, so the
   optional capability `SegmentDescriptionAdapter` (`describe_segment`; `SegmentedAdapter`
   extends it) lets the scan describe the segments the entries named, at the end of the
   pass. A dataset is described from the producer's registry: its Polish title, the
   country of its provider, `dataset_key` the current key and a product that only groups
   it (decision 10); the station catalogs `pl.imgw.stations` and `cz.chmi.stations`, which
   are slots of the store but no datasets of the registry, are named after their provider;
   any other key is not recognised, keeps its own name and has no product. An observation
   is history, never a version, a link or a count: it is kept only when its slot is known
   by the end of its batch (it never makes a slot), a known record costs nothing, and one
   that a pass does not see again is forgotten. Rejected: reading the key from the layout
   (the layout is the producer's knowledge, A-ADR-014); a list of segments for IMGWTools;
   observations as versions (they would change every count and, for an archive, its
   current version).
8. **IMGWTools names the current version of a slot, and the index only asks** (plan I3,
   commit 2). IMGWTools has no links, so no entry says which version of a slot is current.
   The optional capability `CurrentVersionAdapter` (`current_version(root, slot_key)`) asks
   the producer, which reads every sidecar of the slot: the newest `Last-Modified` of an
   archive, the newest download of a series, a catalog or a PMAXTP cell. The index asks once,
   at the end of a pass (`IndexWriter.finish_pass(current=...)`), before its transaction: for
   the slots with a key that the pass touched (a version written, back or gone, a problem
   found or resolved) and for those with a key and no current version of which the pass saw
   a version (the batches are written before `finish_pass`, so a pass that did not finish
   would leave them with none for ever). An unchanged incremental scan asks for no slot; a
   slot with a damaged version is asked at every scan, which costs the producer a read of its
   few sidecars. The answer becomes `slots.current_path` only for a version the pass saw (a
   version published since the listing is taken by the next scan, and the index never holds a
   current path it has no version for, which would read as an orphan link); a slot with a key
   is not unlinked for want of a link. A damaged version in a slot (an invalid sidecar,
   another schema, a size that differs, a stray file) gives no answer: the slot has no
   current version, an older one is not chosen in its place, and the slot is `unreadable`
   with its problem. So does a slot the producer cannot read at all (a link in its path, a
   key it no longer knows), because a slot an earlier pass indexed must not fail the scan
   that finds it gone. A file the system cannot read is an unavailable store, as in a
   listing, and a root that is no store anymore is the producer's error. `missing_sidecar` is
   an interrupted or a running publication, not a version: the older version stays current
   and the problem is explained as non-critical and usually temporary; `unknown_schema` has
   its own text. Rejected: choosing the newest version in Archiwista (the producer's rule,
   A-ADR-014); asking at every scan (a read of every slot, on a share); a current version
   for a version the pass did not see.
9. **A segment is scanned by the producer that owns it** (plan I3, commit 3). A job that
   scans one segment (`ScanRequest.segment`) asks the index which producers described it
   (`segments.producer`, `IndexQueries.segment_producers`) and scans only their directories,
   so a Kartograf segment is never offered to the IMGW directory of the same store. A name
   the index does not know belongs to the producers that scan by segment
   (`SegmentedAdapter`: Kartograf), so a store of only Kartograf behaves as it did before
   the IMGW source. IMGWTools cannot scan one segment (decision 7: `iter_store` has no scope
   below the root, and a pass per dataset would read the whole store once per dataset), so
   for it a segment is a label and a job that names one fails as `unsupported` (message
   `job.segment_scan_unsupported`) before anything is scanned, as the link check does for a
   producer without links; so does a name nobody owns in a store without a producer that
   scans by segment. The IMGW directory is always scanned whole, and an incremental scan of
   it costs only what is new. Rejected: the `ValueError` of `scan_store` (an internal error
   for a valid request that the producer cannot serve); a pass per dataset (above); the
   whole directory for a job that names a segment (the caller asked for less than it gets,
   and the result would name a segment that was not scanned).
10. **An IMGW dataset has its family for a product** (plan I3, commit 3). IMGWTools has no
    products, but the store view and the product list of the Map group segments by product
    and put the ones without under "unknown product" ("Nierozpoznane segmenty"), where
    every IMGW dataset would sit among the segments a plugin did not recognise.
    `describe_segment` therefore gives a dataset the family the registry declares for it
    (`DatasetDescriptor.kind`: `hydro`, `meteo`), the one dataset that has none (PMAXTP) its
    short name, `pmaxtp`, and a station catalog `stations`; a key the registry does not
    know has no product, as an unrecognised segment of Kartograf has none. The product is a
    label that groups datasets, those of both providers together (`hydro` holds IMGW-PIB
    and ČHMÚ, which stay apart in their segments); it follows the segment into the slots,
    the catalog filter `product` and the search. The key stays opaque (SPEC 4.2.1: Archiwista
    never derives a product from it), so the family is the producer's own word for the
    dataset the key names, not a part of the key. Rejected: no product (the store view
    and the Map would call every IMGW dataset unrecognised); the first word of the key (the
    same labels today, by a rule the SPEC forbids); one product `imgw` (hydrological and
    meteorological files, station lists and PMAXTP cells have only their provider in
    common, and `provider` already says it).
11. **The stations are those of each provider's current catalog, read when it changes**
    (plan I4). The optional capability `StationCatalogAdapter` names the provider whose
    catalog a slot is (`station_catalog(slot_key)`: `catalog:<key prefix>.stations` of the
    producer's registry, no disk access) and reads a catalog version
    (`read_stations(root, version)`: IMGWTools' `read_catalog`, which checks the file
    against its sidecar). After a pass over the whole store, outside its transaction,
    the index reads the current version of each provider's catalog only when it is not
    the version its stations came from (`station_catalogs`); a full scan reads every
    catalog again, so a rebuild needs no other trigger. The provider's rows and points
    are replaced in one transaction, so a reader sees the old catalog or the new one. A
    station is its store, provider and code as text (IMGW-PIB codes have nine digits,
    ČHMÚ ones are WIGOS identifiers; the provider of the catalog decides), and a code met
    twice in one catalog keeps its first row. A station without a location keeps the
    catalog's reason (`none`, `zero`, `outside_country`) and has no point (P13,
    A-ADR-022). A provider whose catalog has no current version (gone, or a damaged
    version in it: decision 8) has no stations; a version IMGWTools refuses
    (`ProducerError`) leaves it none as well, with the scan notice `stations_unreadable`,
    and the next scan reads it again; a file the system cannot read makes the store
    unavailable, as a listing does, and the rows stay. The queries (`IndexQueries.stations`,
    commit 2) keep the location groups apart (SPEC 4.3 point 3): a box (`station_points`,
    then the stored coordinates, edges included) takes located stations only, and the
    stations without a location are counted beside it after the attribute filters, never
    narrowed by the box; asking for the group `none` lists them. A river with its
    tributaries (P19) is the range `code <= x < next` over the index of hydrographic codes,
    where `next` follows every text that begins with the code; a code with `-` between its
    parts (ČHMÚ HLGP4) begins with whole parts only, so `1-05` takes `1-05-03-0110` and not
    `1-050-01-0001`, while the IMGW `2138` takes `21382` and never `2139`. Rejected: reading
    the catalogs at every scan (a parse of every station per scan on a share); keeping the
    rows of a version the producer refuses (stations that are no current catalog's); a
    station by code alone (the codes of two providers could meet); `LIKE` or `GLOB` for the
    prefix (their wildcards are characters a code may hold, and a range uses the plain
    index).

**Consequences:** A default installation shows `imgw` as `not_installed` in the sources list
and as a warning of `doctor`. The tests that assumed Kartograf is the only source change;
the tests of the adapter import IMGWTools and are not collected without it. The pinned
commit is not on GitHub yet, so the lock resolves it only where the uv git database of
IMGWTools holds it, and CI cannot be green before IMGWTools is pushed (plan, risks); the
release pull request replaces the commit with the tag. The four things IMGWTools lacked at
its first commit of ADR-007 were requested there (DEV-17.5) and are met at the pinned
commit: a machine code of each problem in `StoreInfo.problem_codes`, the `producer` and
`producer_version` of a sidecar in `Meta`, `iter_store(skip_versions=)` in the shape of
`ScanScope.known_versions` (an incremental scan reads no sidecar of a known version) and
one rule for a marker (the reader needs only its `schema`, as `open_store` does). A store
takes an IMGW directory beside or instead of its Kartograf one (the settings step of the
same plan, `StoreConfig.imgw`): the scan indexes its files as versions of their slots,
with the current version IMGWTools names (decision 8); a source that is not available has its directory skipped and its
entry kept (SPEC 5.8); and a directory that lies in a store of any producer or holds one is
refused by the marker file names at its own field (DEV-19.14), looking two levels down
because the producer's writer, which looks at the whole tree, is not run by a settings
change. The index keeps the stations of each provider's current catalog (decision 11);
the series coverage comes after them.

**Errata:** none.
