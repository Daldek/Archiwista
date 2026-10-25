# ADR-033: Offer the producer's default root in the wizard, and never use it

**Date:** 2026-10-25
**Status:** proposed (done on the topic branch `feature/kartograf-data-output`; decision D7 of the plan `docs/plans/2026-10-25-archiwista-next.md` was accepted by delegated approval; accepted when the author approves and merges the branch)

**Context:** The data-output convention (Nogat DEV §19, ECO-051) gives every producer a default store root: `KARTOGRAF_ROOT`, `[kartograf] root` of `nogat.toml`, else `<data_dir>/kartograf` (DEV-19.2; IMGWTools has `IMGW_ROOT` and `<data_dir>/imgw`). A producer call that names no root reads and writes there. Archiwista names the store in every call it makes (Decision 1 of the plan), so it never needs the default. A person who has used Kartograf's command line, however, already has a store in that directory, and the first-run wizard asks for a directory that this person would have to find and type. Kartograf first reported its default only through `kartograf.get_config()`: `store.root`, its `source`, `name`, `exists` and `size_bytes`, the sum of every file below the root, so one report was a walk of the whole store (the request for a read-only `store_root()` in `kartograf.__all__` was filed in the plan). Kartograf `45dedf4a` has it: `store_root()` returns `StoreRoot(root, source, name, marker_exists)`, in the order of DEV-18.1 and without reading the store.

**Options:**
- A) Offer it (D7): an optional capability of the adapter reports the default root; `GET /sources` carries it; the wizard shows it under an empty Kartograf field when it exists and holds the marker, and a click enters it.
- B) Fill the field with it at once. Rejected: a saved setting would then follow from not looking, and an empty field is the check that somebody chose a directory.
- C) Read `nogat.toml` and the variables in Archiwista. Rejected: it copies the precedence of the producer (DEV-18.1) and would answer the open question of whether Archiwista reads `nogat.toml` (PROGRESS) through a side door.
- D) Use the default root for a store that is not configured. Rejected: Decision 1 (store mode only, no call without its root).
- E) Report it in `/health`. Rejected: the state is polled every 2 seconds while a store is scanned, and a producer may do work for each report (`get_config()` walked the whole root).

**Decision:** A.

1. **A capability, not a method of every adapter.** `DefaultRootAdapter.default_root() -> DefaultRoot` (`sources/protocol.py`, optional like `SegmentedAdapter`) gives `path`, `source`, `name`, `exists` and `marked`. The Kartograf adapter takes them from `kartograf.store_root()` (`root`, `source`, `name`, `marker_exists`) and `exists` from one `is_dir()`; `marked` is whether `kartograf-store.json` is a file there, as Kartograf says it (nothing more: the wizard offers a store, and the probe judges it when it is saved). A producer without the capability, an unavailable plugin and a plugin whose report fails have none (`sources.registry.read_default_root`; a failure is logged, because an offer must not stop its caller).
2. **Offered, never entered, never used.** The wizard shows the directory, the layer of the settings that gave it and the button "Użyj tego katalogu" under a store's empty field, once, while a store has no directory. Nothing is saved before the person clicks and saves, and nothing in Archiwista passes the default root to a producer or writes into it. The tests prove the second half: since M4 every test runs with the default roots pointed at a canary tree, and a test fails when anything appears in it.
3. **On demand only.** `GET /sources` (also `archiwista sources`, same model: `SourceListItem` with `default_root`) and `archiwista doctor` ask for it; `/health` and `archiwista status` do not, and the wizard asks `/sources` only while a store waits for its directory. The report is for an answer a person waits for, though it is cheap: `store_root()` reads no store, where `get_config()` sized the root by walking all of it. The request to Kartograf (plan "Requests") for a read-only `store_root()` in `kartograf.__all__` is closed by the pin `45dedf4a`.
4. **Texts.** The description of the root (`default_root.message`, the doctor line) is a catalog message (`doctor.default_root` and its parts, both languages); the wizard builds its own Polish sentence from the fields.

**Consequences:**
- The wizard becomes optionally shorter for a person who has Kartograf's store in its default place and has run `kartograf store init` once; every other case is as before.
- The report costs two `stat` calls and no walk of the store, however large it is (a first version used `get_config()`, which sizes the root, and was replaced by `store_root()` as soon as Kartograf had it).
- The IMGW adapter (step I1) implements the same capability from `IMGW_ROOT` and `<data_dir>/imgw`; the wizard offers it under the IMGW field then.
- A broken `nogat.toml` is not raised by `store_root()` (as it was not by `get_config()`), so the root is then the one the environment and the default give; the wizard offers it only when it is a store, and a saved directory is probed as any other.
