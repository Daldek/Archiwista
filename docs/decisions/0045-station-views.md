# ADR-045: The station views: the routes they read and how the interface draws them

**Date:** 2026-10-26
**Status:** proposed (plan `docs/plans/2026-10-25-archiwista-next.md` Part 4, written with the defaults of D12 while its approval is open; done on the topic branch `feature/kartograf-data-output`; accepted when the author approves the plan and merges the branch)

**Context:** I6 (ADR 0032 decision 13) gave the stations of the station catalogs and the coverage of their series to agents and scripts: `GET /stations`, the card, the Timeline of one station and `GET /map/stations`. The interface had no view of them. The author answered the mockup questions M5 and M11 on 2026-10-26 (SPEC 4.8.4, 6.5 i to k and m, 6.7, 6.8): a point's shape says the station type and its fill the coverage of one variable, clusters are neutral, the Timeline is a tab of the Catalog, the comparison stacks one panel per station. Part 4 builds the read side of the station views of SPEC 13 "v0.5" on those routes, step by step (I8.1 to I8.6); each step adds a decision here.

**Options (for the whole part):**
- A) The interface reads only what the routes give, and each step adds the route it lacks (the datasets, the Timeline of a page, the series values, the comparison). Chosen: the CLI and agents get the same answers (SPEC 9), and the index stays the only source of labels.
- B) The interface derives what it needs from `GET /products` and the card of each station (the variables from the first station's series, the Timeline by one request per station). Rejected: a dataset's variables are not those of one station, and a page of 200 stations would be 200 requests.
- C) A chart library for the station chart. Rejected (D12): the interface has no build step (A-ADR-028) and the vendored libraries have no chart; an SVG drawn by the module is enough for two axes and the gap bands.

**Decision:** A, in the steps of Part 4.

1. **The datasets and the station type (I8.1, commit 1).** `GET /stations/datasets` (and `archiwista stations datasets`) lists the datasets with station series in the index, one per store and dataset of `series_catalogs`, by store and key: the dataset key, the producer's name of the segment of its series slot, provider, family, time unit, the default year type of its labels and R by default in it (`default_span`, as the labels count it), the label of the current series version with its `series.json`, and its variables (key, variable, unit, half-year period): the distinct keys of `station_series` in the order of the series index (`IndexQueries.station_datasets`). The interface's dataset chip and "Kolor punktów" read it, never a key's text (SPEC 4.2.1). `GET /stations` and `GET /map/stations` gain the repeatable `meteo_kind` (`synoptic`, `climate`, `precipitation`; `MeteoKind`, `METEO_KINDS`): the type chips filter on the server, so the counts and the grid count what the chips show; a station of no such kind (a water gauge, a ČHMÚ meteo station without a kind) is left out while the filter is given. The fixed paths are declared before `/stations/{code}`.

**Consequences:**
- The variables of a dataset are those its stations' series hold (the same set `imgwtools.summarize_series` gives); their order is that of the series index, which IMGWTools writes by key, not the registry's (P before Tmax for ČHMÚ meteo data, H, Q, T for hydro data). The first one is the default colour of the points (D12).
- A dataset whose series version is known but whose stations have no series lists no variables; the map then has no colour to choose.
- `meteo_kind` takes part in the cursor of `GET /stations`: a cursor of another selection of types is refused like any other.
