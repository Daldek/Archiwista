/**
 * The stations of a product of the station producer (`imgw`) in the Catalog
 * (docs/SPEC.md 6.8, sketch 6.5 m; plan I8.2, ADR-045): `GET /stations` page
 * by page (200 rows, the cursor) with the filters of the address, along
 * rivers unless the address asks for the order by name (`sort`).
 *
 * A station is a row with a line per variable of its series: the label of
 * SPEC 4.8.4 with its fill in the station's shape (`StationSymbol`) and its
 * full years (P16; a station has no single label). The columns are those of
 * sketch 6.5 m: the station and its type, the code, the river with its code,
 * the coverage and the location (its source, or the catalog's reason without
 * one).
 *
 * The stations with a position come first, as a group with its count; „Bez
 * położenia” is the last group, read with `location=none` once the located
 * ones are all loaded, collapsed when more than 50 stations are located and
 * expanded when the address asks for `location=none` (the map's counter,
 * M5). Its rows never lead to the map. Enter or a click opens a station's
 * card (views/station.js, `station` of the address), on a group row folds
 * it; M and the row's button show a located station on the map.
 *
 * „Oś czasu” (`layout=timeline`, plan I8.3) is the other layout of the same
 * toolbar and filters: `GET /stations/timeline` of one dataset (the
 * address's, else the product's first) in one cursor of the address's
 * location group, drawn as stations × years
 * (views/catalog-station-timeline.js), whose station names open the card too.
 */

import { listStations, listStationTimeline } from "../api.js";
import { count, int } from "../format.js";
import { catalog as L } from "../labels/catalog.js";
import { T, t } from "../labels/index.js";
import {
  STATION_KINDS,
  STATION_PARAM,
  StationSymbol,
  stationAddress,
  stationShape,
  stationType,
} from "../map/stations.js";
import { href, Link, navigate, setParams } from "../router.js";
import { findView } from "../routes.js";
import {
  html,
  Icon,
  ProblemView,
  Seg,
  Spinner,
  Tech,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "../ui.js";
import { CatalogGrid } from "./catalog-grid.js";
import { StationTimeline, timelineDataset, timelinePage } from "./catalog-station-timeline.js";
import { LAYOUT_PARAM, TIMELINE_LAYOUT, ViewSwitch } from "./switch.js";

const S = L.stations;
/** Rows of a page: the API's maximum. */
const PAGE = 200;
/** Above this many located stations „Bez położenia” starts collapsed (SPEC 6.8, M5). */
const COLLAPSE_ABOVE = 50;
/** Height of a line of a station's row and the row's padding, px (catalog.css `.st-line`). */
const LINE = 18;
const PAD = 10;
/** Height of a group's heading row, px (catalog.css `.st-group-row`). */
const GROUP_ROW = 34;
/** Zoom of the map showing one station. */
const STATION_ZOOM = 11;
const SORTS = ["river", "name"];
const LOCATIONS = ["any", "with", "none"];
/** The layouts of the stations: the list (the default, M3) and the Timeline. */
const LAYOUTS = [
  { value: "list", label: L.layouts.list, icon: "table", title: S.layouts.list_title },
  { value: "timeline", label: L.layouts.timeline, icon: "chart", title: S.layouts.timeline_title },
];

/** Parameters the filter panel sets for stations; „Wyczyść filtry” removes them. */
export const STATION_FILTERS = [
  "store",
  "product",
  "dataset",
  "years",
  "kind",
  "meteo_kind",
  "active",
  "river_code",
  "river_scope",
  "variable",
  "coverage",
  "min_complete_years",
  "area_id",
  "bbox",
  "bbox_crs",
  "boundary",
];

/**
 * The filters of an address shown as chips while the panel is closed and
 * counted on its button: not the product, which is the list itself.
 *
 * @param {Object<string, string>} params - Route parameters.
 * @returns {string[]}
 */
export function activeStationFilters(params) {
  return STATION_FILTERS.filter((name) => params[name] && name !== "product");
}

/**
 * The parameters of `GET /stations` of an address: the station kind is the
 * product's when the product is one (`hydro`, `meteo`); repeatable ones are
 * comma lists in the address. `location`, the page and the cursor are the
 * list's own.
 *
 * @param {Object<string, string>} params - Route parameters.
 * @param {string|null} product - The product of the address.
 * @returns {import("../types.js").StationListFilters}
 */
export function stationQuery(params, product) {
  const list = (name) => (params[name] ? params[name].split(",").filter(Boolean) : []);
  return {
    store: params.store ?? null,
    dataset: params.dataset ?? null,
    years: params.years ?? null,
    year_type: params.year_type ?? null,
    kind: STATION_KINDS.includes(product) ? product : (params.kind ?? null),
    meteo_kind: list("meteo_kind"),
    active: params.active ?? null,
    river_code: params.river_code ?? null,
    river_scope: params.river_code && params.river_scope ? params.river_scope : null,
    variable: list("variable"),
    coverage: list("coverage"),
    min_complete_years: list("min_complete_years"),
    q: params.q ?? null,
    sort: SORTS.includes(params.sort) ? params.sort : null,
    area_id: params.area_id ?? null,
    bbox: params.bbox ?? null,
    bbox_crs: params.bbox ? (params.bbox_crs ?? null) : null,
    boundary: params.boundary === "false" ? false : null,
  };
}

/**
 * The family whose remembered year type numbers the list without `year_type`,
 * as the API chooses it: the dataset's, else the station kind's, else meteo
 * for the meteo types, else hydro (a list of both families, P15).
 *
 * @param {import("../types.js").StationListFilters} query - Of `stationQuery`.
 * @param {import("../types.js").StationDataset[]} datasets
 * @returns {"hydro"|"meteo"}
 */
export function stationFamily(query, datasets) {
  const dataset = datasets.find((item) => item.dataset === query.dataset);
  if (dataset?.kind === "hydro" || dataset?.kind === "meteo") return dataset.kind;
  if (query.kind === "hydro" || query.kind === "meteo") return query.kind;
  return query.meteo_kind.length ? "meteo" : "hydro";
}

/**
 * The stations of the Catalog: the toolbar, then the groups and rows of the
 * list or the Timeline (`layout=timeline`), and the footer.
 *
 * @param {object} props
 * @param {Object<string, string>} props.params - Route parameters.
 * @param {string} props.product - The product of the address (a station product).
 * @param {import("../types.js").StationDataset[]} props.datasets - Of the product.
 * @param {boolean} props.datasetsRead - `GET /stations/datasets` answered or failed.
 * @param {Map<string, string>|null} props.storeNames - Store names with several stores.
 * @param {*} props.toggle - The filter panel's button.
 * @param {*} props.search - The search field (`q`).
 * @param {boolean} props.panel - Whether the filter panel is open.
 * @param {string} props.indexStamp - Changes when a store's index changes.
 * @param {boolean} props.narrow - Phone layout.
 * @param {{current: *}} props.grid - Receives the grid's `{focusRow(index)}`.
 */
export function CatalogStations(props) {
  const { params, product, datasets, datasetsRead, storeNames, toggle, search } = props;
  const { panel, indexStamp, narrow, grid } = props;
  const timeline = params[LAYOUT_PARAM] === TIMELINE_LAYOUT;
  const listed = stationQuery(params, product);
  // The Timeline shows one dataset and asks for fewer stations of a dataset of many variables.
  const datasetKey = timeline ? timelineDataset(params, datasets) : null;
  const dataset = datasets.find((item) => item.dataset === datasetKey) ?? null;
  const query = timeline
    ? { ...listed, dataset: datasetKey, limit: timelinePage(dataset, listed.variable) }
    : listed;
  const location = LOCATIONS.includes(params.location) ? params.location : "any";
  const key = JSON.stringify({ ...query, location, timeline });
  const stable = useMemo(() => query, [key]);
  const order = timeline ? [location] : groupsOf(location);
  const pages = useStationPages(stable, key, order, timeline ? listStationTimeline : listStations, {
    enabled: !timeline || (datasetKey !== null && datasetsRead),
  });
  const [folded, setFolded] = useState({ key: null, open: true });
  const counts = pages.counts;
  const area = Boolean(query.area_id || query.bbox);
  const open =
    folded.key === key
      ? folded.open
      : location === "none" || counts === null || counts.located <= COLLAPSE_ABOVE;
  const foldable = order.length > 1;
  const toggleGroup = () => foldable && setFolded({ key, open: !open });
  // The Timeline reads its one group to the end; the list „Bez położenia” only while open.
  const reading = timeline || open;
  useIndexRefresh(indexStamp, pages);

  const items = useMemo(() => {
    const rows = [];
    if (counts === null) return rows;
    if (timeline) return pages.parts[location].items;
    if (order.includes("with") && counts.located) {
      rows.push({ group: "with", count: counts.located, boundary: counts.boundary, area });
      rows.push(...pages.parts.with.items);
    }
    if (order.includes("none") && counts.unlocated && (order[0] === "none" || pages.parts.with.done)) {
      rows.push({ group: "none", count: counts.unlocated, open, foldable });
      if (open) rows.push(...pages.parts.none.items);
    }
    return rows;
  }, [pages.parts, counts, open, key]);
  const total =
    counts === null
      ? null
      : (order.includes("with") && counts.located ? 1 + counts.located : 0) +
        (order.includes("none") && counts.unlocated ? 1 + (open ? counts.unlocated : 0) : 0);
  const located = counts && location !== "none" ? counts.located : 0;
  const unlocated = counts && location !== "with" ? counts.unlocated : 0;
  const stations = counts === null ? null : located + unlocated;
  // Rows to load: the stations without a position only while their group is open.
  const wanted = located + (reading ? unlocated : 0);
  const loaded = order.reduce((sum, group) => sum + pages.parts[group].items.length, 0);
  const map = findView("map")
    ? (item) =>
        navigate("map", {
          product,
          store: item.store,
          dataset: params.dataset,
          meteo_kind: params.meteo_kind,
          year_type: params.year_type,
          center: `${item.location.lon},${item.location.lat}`,
          zoom: STATION_ZOOM,
        })
    : null;
  const openCard = (item) => setParams({ [STATION_PARAM]: stationAddress(item) });
  const cardHref = (item) => href("catalog", { ...params, [STATION_PARAM]: stationAddress(item) });
  // Enter or a click: a station's card; the heading of „Bez położenia” folds it.
  const openRow = (item) => {
    if (item.group === "none") toggleGroup();
    else if (!item.group) openCard(item);
  };
  const selected = params[STATION_PARAM] ?? null;
  const datasetNames = new Map(datasets.map((item) => [item.dataset, item.name ?? item.dataset]));
  const active = activeStationFilters(params);
  const sort = query.sort ?? "river";
  const api = apiAddress(stable, location, timeline ? "/stations/timeline" : "/stations");
  const layout = (value) =>
    setParams({ [LAYOUT_PARAM]: value === "list" ? null : TIMELINE_LAYOUT });
  const empty = html`<${Empty} counts=${counts} location=${location} />`;
  let body;
  if (pages.error) {
    body = html`<div class="cat-problem"><${ProblemView} problem=${pages.error.problem} /></div>`;
  } else if (timeline && datasetKey === null) {
    body = html`<div class="cat-empty">${datasetsRead
      ? html`<div class="cat-empty-box"><p>${S.timeline.no_dataset}</p></div>`
      : html`<${Spinner} label=${L.result.loading} />`}</div>`;
  } else if (timeline) {
    body = html`<${StationTimeline} items=${items} total=${stations} hasMore=${pages.hasMore(true)}
      loading=${pages.loading} loadingMore=${pages.loadingMore} moreError=${pages.moreError}
      onMore=${() => pages.more(true)} resetKey=${key} datasetKey=${datasetKey} dataset=${dataset}
      chosen=${Boolean(params.dataset)} color=${params.color ?? null}
      onColor=${(value) => setParams({ color: value })} onOpen=${openCard} cardHref=${cardHref}
      handle=${grid} empty=${empty} />`;
  } else {
    body = html`<${CatalogGrid} rows=${STATION_ROWS} items=${items} total=${total}
      hasMore=${pages.hasMore(open)} loading=${pages.loading} loadingMore=${pages.loadingMore}
      moreError=${pages.moreError} onMore=${() => pages.more(open)} resetKey=${key} narrow=${narrow}
      handle=${grid} isSelected=${(item) => !item.group && stationAddress(item) === selected}
      cardOpen=${selected !== null} onOpen=${openRow} onMap=${map}
      onToggle=${toggleGroup} sort=${sort} storeNames=${storeNames} datasetNames=${datasetNames}
      empty=${empty} />`;
  }

  return html`<section class="cat" aria-label=${L.title}>
    <div class="cat-toolbar">
      <div class="cat-toolbar-row">
        <${ViewSwitch} current="catalog" params=${params} />
        <${Seg} small label=${L.layouts.label} value=${timeline ? "timeline" : "list"}
          onChange=${layout} options=${LAYOUTS} />
        <span class="cat-spacer"></span>
        <${Seg} small label=${S.order} value=${sort}
          onChange=${(value) => setParams({ sort: value === "river" ? null : value })}
          options=${[
            { value: "river", label: S.order_river, title: S.order_river_title },
            { value: "name", label: S.order_name, title: S.order_name_title },
          ]} />
      </div>
      <div class="cat-toolbar-row">${toggle}${search}</div>
      <div class="cat-toolbar-row">
        <${Groups} counts=${counts} location=${location} area=${area} />
        <span class="cat-spacer"></span>
        ${stations === null
          ? null
          : html`<span class="cat-summary">
              <b class="tabular">${count(stations, S.count)}</b>
              ${loaded < wanted
                ? html`<span class="faint tabular">${t(L.result.loaded, { loaded: int(loaded), total: int(stations) })}</span>`
                : null}
            </span>`}
        ${map && location !== "none"
          ? html`<${Link} view="map" params=${mapParams(params)} class="btn sm" title=${S.show_on_map_all_title}>
              <${Icon} name="map" size=${14} />${S.show_on_map_all}</${Link}>`
          : null}
        <span class="cat-api"><${Tech} value=${[[L.result.api_title, api]]}>
          <span class="faint">${L.result.api}</span></${Tech}></span>
      </div>
      ${!panel && active.length ? html`<${ActiveFilters} names=${active} params=${params} />` : null}
      <${Notes} counts=${counts} location=${location} pages=${pages} />
    </div>
    <div class="cat-body">${body}</div>
    <footer class="cat-foot">
      ${pages.moreError
        ? html`<span class="cat-more-error" role="alert">${L.result.more_failed}
            <button type="button" class="btn sm" onClick=${() => pages.more(reading)}>
              ${T.common.actions.retry}</button></span>`
        : null}
      <span class="cat-keys" id="cat-keys">
        ${L.grid.keys}
        ${timeline
          ? html` ${S.timeline.keys} `
          : html`<span class="kbd">↑</span><span class="kbd">↓</span> ${L.grid.key_move} ·
              <span class="kbd">Enter</span> ${S.key_open} ·
              ${map ? html`<span class="kbd">M</span> ${L.grid.key_map} · ` : null}`}
        <span class="kbd">Ctrl K</span> ${L.grid.key_search}
      </span>
    </footer>
    <div class="visually-hidden" role="status" aria-live="polite">
      ${pages.loading || stations === null ? "" : t(L.result.announce, { count: count(stations, S.count) })}
    </div>
  </section>`;
}

/** The location groups of the list in their order: located, then „Bez położenia”. */
function groupsOf(location) {
  if (location === "none") return ["none"];
  return location === "with" ? ["with"] : ["with", "none"];
}

/** The location groups with their counts: a group is the `location` filter. */
function Groups({ counts, location, area }) {
  const G = S.groups;
  const totals = counts
    ? { any: counts.located + counts.unlocated, with: counts.located, none: counts.unlocated }
    : { any: null, with: null, none: null };
  const titles = { any: null, with: G.with_title, none: G.none_title };
  return html`<div class="cat-groups" role="group" aria-label=${G.label}>
    <span class="cat-groups-label">${G.label}:</span>
    ${LOCATIONS.map(
      (group) => html`<button type="button" key=${group}
        class=${`chip cat-group ${group}${group === location ? " on" : ""}`}
        aria-pressed=${group === location ? "true" : "false"} title=${titles[group]}
        onClick=${() => setParams({ location: group === "any" ? null : group })}>
        ${group === "with" && area ? G.with_area : G[group]}${" "}<span class="cat-count tabular">${totals[group] === null ? "…" : int(totals[group])}</span>
      </button>`,
    )}
  </div>`;
}

/** Active filters as chips while the panel is closed; × removes one. */
function ActiveFilters({ names, params }) {
  return html`<div class="chip-row cat-active" role="group" aria-label=${L.filters.active}>
    ${names.map((name) => {
      const label = S.filters[name] ?? L.filters[name] ?? name;
      const text = typeof label === "string" ? label : name;
      return html`<button type="button" key=${name} class="chip" onClick=${() => setParams({ [name]: null })}
        title=${t(L.filters.remove, { name: text })} aria-label=${t(L.filters.remove, { name: text })}>
        <span class="muted">${text}:</span> <b>${params[name]}</b>
        <${Icon} name="x" size=${12} />
      </button>`;
    })}
  </div>`;
}

/** Notes above the list: the stations the coverage filters hide, the group without a position, a changed index. */
function Notes({ counts, location, pages }) {
  const hidden = counts?.hidden ?? 0;
  if (!hidden && location !== "none" && !pages.indexChanged) return null;
  return html`<div class="cat-notes">
    ${hidden
      ? html`<p class="hint cat-hidden-note" role="note"><${Icon} name="info" size=${14} /> ${t(S.hidden, { count: int(hidden) })}</p>`
      : null}
    ${location === "none"
      ? html`<p class="hint cat-none-note" role="note"><${Icon} name="info" size=${14} /> ${S.none_note}</p>`
      : null}
    ${pages.indexChanged
      ? html`<p class="hint cat-index-note"><${Icon} name="rotate" size=${14} />
          ${L.result.index_changed}
          <button type="button" class="btn sm" onClick=${pages.reload}>${L.result.refresh}</button></p>`
      : null}
  </div>`;
}

/** The empty list: why, and what to change. */
function Empty({ counts, location }) {
  const others = location === "any" || !counts ? 0 : counts.located + counts.unlocated;
  return html`<div class="cat-empty-box">
    <p>${others ? t(S.empty_group, { group: S.groups[location] }) : S.empty}</p>
    ${others
      ? html`<button type="button" class="btn sm" onClick=${() => setParams({ location: null })}>
          ${t(L.result.show_all, { count: int(others) })}</button>`
      : null}
  </div>`;
}

/**
 * Pages of the stations: the groups of `order` one after the other
 * (`location=with`, then `none`; the Timeline's one group), each paged by its
 * cursor. The first page of the first group is read when the query changes;
 * `more(open)` reads the next page of the first group not read to its end,
 * the group „Bez położenia” of the list only while it is open. Until the
 * first page of a new query arrives, the rows of the previous one stay,
 * marked `loading`. Nothing is asked while `enabled` is false.
 *
 * @param {import("../types.js").StationListFilters} query
 * @param {string} key - Changes with the query and the location group.
 * @param {Array<"any"|"with"|"none">} order - The groups, in the order of the rows.
 * @param {(filters: object, options: {signal: AbortSignal}) => Promise<*>} list - Reads a
 *   page: `listStations` or `listStationTimeline`.
 * @param {{enabled: boolean}} options
 */
function useStationPages(query, key, order, list, { enabled }) {
  const [state, setState] = useState(() => fresh(null));
  const live = useRef({ controller: null, busy: false });
  Object.assign(live.current, { key, query, order, list, state });

  const read = (group, cursor, { quiet = false } = {}) => {
    const run = live.current;
    run.controller?.abort();
    const controller = new AbortController();
    run.controller = controller;
    run.busy = true;
    const first = cursor === null && group === run.order[0];
    const requested = run.key;
    setState((previous) => ({
      ...previous,
      loading: first && !quiet,
      loadingMore: !first,
      moreError: null,
      error: first ? null : previous.error,
      indexChanged: first ? false : previous.indexChanged,
    }));
    const filters = { limit: PAGE, ...run.query, location: group, ...(cursor ? { cursor } : {}) };
    run.list(filters, { signal: controller.signal }).then(
      (page) => {
        if (controller.signal.aborted) return;
        run.busy = false;
        setState((previous) => {
          const base = first ? fresh(requested) : previous;
          const part = base.parts[group];
          return {
            ...base,
            key: requested,
            parts: {
              ...base.parts,
              [group]: {
                items: cursor ? [...part.items, ...page.items] : page.items,
                next: page.next_cursor,
                done: page.next_cursor === null,
              },
            },
            counts: page.counts,
            error: null,
            moreError: null,
            loading: false,
            loadingMore: false,
            pages: base.pages + 1,
          };
        });
      },
      (error) => {
        if (controller.signal.aborted || error?.name === "AbortError") return;
        run.busy = false;
        setState((previous) =>
          first
            ? { ...fresh(requested), error, loading: false }
            : { ...previous, moreError: error, loadingMore: false },
        );
      },
    );
  };

  useEffect(() => {
    if (!enabled) return undefined;
    read(order[0], null);
    return () => live.current.controller?.abort();
  }, [key, enabled]);

  /** The group whose next page comes, or null. */
  const pending = (open) => {
    const run = live.current;
    const current = run.state;
    if (current.counts === null || current.key !== run.key) return null;
    const group = run.order.find((name) => !current.parts[name].done);
    if (group === undefined) return null;
    if (group === "none" && (current.counts.unlocated === 0 || (run.order.length > 1 && !open))) return null;
    return group;
  };

  return {
    ...state,
    loading: state.loading || state.key !== key,
    hasMore: (open) => pending(open) !== null,
    more: (open) => {
      const group = pending(open);
      if (group !== null && !live.current.busy) read(group, live.current.state.parts[group].next);
    },
    reload: () => enabled && read(order[0], null),
    quietReload: () => enabled && read(order[0], null, { quiet: true }),
    markIndexChanged: () => setState((previous) => ({ ...previous, indexChanged: true })),
  };
}

/** The state of a query before any of its pages. */
function fresh(key) {
  const part = () => ({ items: [], next: null, done: false });
  return {
    key,
    parts: { any: part(), with: part(), none: part() },
    counts: null,
    error: null,
    moreError: null,
    loading: true,
    loadingMore: false,
    pages: 0,
    indexChanged: false,
  };
}

/**
 * Follow the index: after a scan the first page is read again quietly; a
 * list scrolled further gets a note with „Odśwież listę” instead.
 */
function useIndexRefresh(indexStamp, pages) {
  const seen = useRef(indexStamp);
  useEffect(() => {
    const previous = seen.current;
    seen.current = indexStamp;
    if (!previous || previous === indexStamp || pages.loading) return;
    if (pages.pages <= 1) pages.quietReload();
    else pages.markIndexChanged();
  }, [indexStamp]);
}

/** The rows of stations and of their groups' headings. */
const STATION_ROWS = {
  label: S.grid,
  columns: () => 6,
  layout: () => "stations",
  Header: StationHeader,
  Cells: StationCells,
  height: (item, narrow) =>
    item.group ? GROUP_ROW : PAD + LINE * (narrow ? lineCount(item) + 2 : Math.max(2, lineCount(item))),
  key: (item) => (item.group ? `group:${item.group}` : `${item.store}/${item.provider}/${item.code}`),
  className: (item) => (item.group ? "st-group-row" : item.location.kind === "point" ? "" : "unlocated"),
  mappable: (item) => !item.group && item.location.kind === "point",
};

/** The lines of a station's coverage: one per variable of each series, at least one. */
function lineCount(item) {
  const lines = item.series.reduce((sum, series) => sum + Object.keys(series.coverage).length, 0);
  return Math.max(1, lines);
}

function StationHeader({ sort }) {
  const sorted = (name) => (sort === name ? "ascending" : null);
  return html`<div role="columnheader" class="cell c-st" aria-sort=${sorted("name")}
      title=${sort === "name" ? S.sorted_name : null}>
      ${S.station}${sort === "name" ? html`<${Icon} name="down" size=${12} />` : null}
    </div>
    <div role="columnheader" class="cell c-code">${S.code}</div>
    <div role="columnheader" class="cell c-river" aria-sort=${sorted("river")}
      title=${sort === "river" ? S.sorted_river : null}>
      ${S.river}${sort === "river" ? html`<${Icon} name="down" size=${12} />` : null}
    </div>
    <div role="columnheader" class="cell c-cov">${S.coverage}</div>
    <div role="columnheader" class="cell c-loc">${S.location}</div>
    <div role="columnheader" class="cell c-act"><span class="visually-hidden">${L.grid.actions}</span></div>`;
}

/**
 * The cells of a station's row, or the heading of its group.
 *
 * @param {{item: *, props: object}} props - `props`: the grid's (`onMap`,
 *   `onToggle`, `storeNames`, `datasetNames`).
 */
function StationCells({ item, props }) {
  if (item.group) return groupHeading(item, props);
  const located = item.location.kind === "point";
  const name = item.name ?? S.unnamed;
  const store = props.storeNames ? ` · ${props.storeNames.get(item.store) ?? item.store}` : "";
  return html`<div role="gridcell" class="cell c-st">
      <span class="st-line st-name ell" title=${name}>${name}</span>
      <span class="st-line cell-sub"><${StationSymbol} shape=${stationShape(item)} state="shape" size=${12} />
        ${stationType(item)}${item.active === false ? ` · ${S.historical}` : ""}</span>
    </div>
    <div role="gridcell" class="cell c-code">
      <span class="st-line mono ell">${item.code}</span>
      <span class="st-line cell-sub">${item.provider}${store}</span>
    </div>
    <div role="gridcell" class="cell c-river">
      <span class="st-line ell" title=${item.river ?? ""}>${item.river ?? "–"}</span>
      <span class="st-line cell-sub mono">${item.hydrographic_code ?? ""}</span>
    </div>
    <div role="gridcell" class="cell c-cov">${coverageLines(item, props.datasetNames)}</div>
    <div role="gridcell" class="cell c-loc">${stationLocation(item)}</div>
    <div role="gridcell" class="cell c-act">
      ${located && props.onMap
        ? html`<button type="button" class="btn ghost icon-btn cat-map" tabindex="-1"
            title=${t(S.show_on_map, { name })} aria-label=${t(S.show_on_map, { name })}
            onClick=${() => props.onMap(item)}><${Icon} name="map" size=${15} /></button>`
        : null}
    </div>`;
}

/** A group's heading: its name and count; „Bez położenia” folds. */
function groupHeading(item, props) {
  const G = S.group;
  if (item.group === "with") {
    return html`<div role="gridcell" class="cell st-group" aria-colspan="6">
      <span class="st-group-name">${item.area ? G.with_area : G.with}${" "}<span class="cat-count tabular">${int(item.count)}</span></span>
      ${item.area && item.boundary ? html`<span class="faint">${t(G.boundary, { count: int(item.boundary) })}</span>` : null}
    </div>`;
  }
  const title = html`${G.none} <span class="cat-count tabular">${int(item.count)}</span>`;
  return html`<div role="gridcell" class="cell st-group none" aria-colspan="6">
    ${item.foldable
      ? html`<button type="button" class="btn ghost sm st-group-name" tabindex="-1" aria-expanded=${item.open ? "true" : "false"}
          title=${item.open ? G.collapse : G.expand} onClick=${props.onToggle}>
          <${Icon} name=${item.open ? "down" : "chevron"} size=${13} />${title}</button>`
      : html`<span class="st-group-name">${title}</span>`}
    <span class="faint">— ${G.none_note}</span>
  </div>`;
}

/** A line per variable of each series: the fill of its state, its key, label and full years. */
function coverageLines(item, datasetNames) {
  if (!item.series.length) return html`<span class="st-line faint">${S.no_series}</span>`;
  const several = item.series.length > 1;
  const shape = stationShape(item);
  return item.series.flatMap((series) =>
    Object.values(series.coverage).map(
      (variable) => html`<span class="st-line st-var" key=${`${series.dataset}/${variable.key}`}
        title=${t(S.variable_title, { variable: variable.variable, unit: variable.unit, label: variable.label })}>
        <${StationSymbol} shape=${shape} state=${variable.state} size=${12} />
        ${several ? html`<span class="faint">${datasetNames.get(series.dataset) ?? series.dataset} · </span>` : null}
        <b class="st-key">${variable.key}</b>
        <span class="st-label">${variable.label}</span>
        <span class="faint st-full"> · ${count(variable.complete_years, S.full_years)}</span>
      </span>`,
    ),
  );
}

/** The location: its source, or the catalog's reason without a position (the code in the title). */
function stationLocation(item) {
  const { kind, reason, source, on_boundary: boundary } = item.location;
  if (kind === "point") {
    const text = `${S.source[source] ?? source ?? ""}${boundary ? ` · ${S.on_boundary}` : ""}`;
    return html`<span class="st-line"><span class="cat-loc footprint">${S.located}</span></span>
      <span class="st-line cell-sub" title=${source ? `${text} (${source})` : text}>${text}</span>`;
  }
  const text = S.reason[reason] ?? reason ?? "";
  return html`<span class="st-line"><span class="cat-loc none">${S.unlocated}</span></span>
    <span class="st-line cell-sub" title=${reason ? `${text} (${reason})` : text}>${text}</span>`;
}

/** The map of the stations: the same product, store, years, area and station choices. */
function mapParams(params) {
  const names = [
    "product",
    "store",
    "years",
    "area_id",
    "dataset",
    "color",
    "meteo_kind",
    "year_type",
    "boundary",
  ];
  return Object.fromEntries(names.filter((name) => params[name]).map((name) => [name, params[name]]));
}

/** The API's address of the rows: `path` (`/stations`, `/stations/timeline`) with the query. */
function apiAddress(query, location, path) {
  const search = new URLSearchParams();
  for (const [name, value] of Object.entries({ ...query, location: location === "any" ? null : location })) {
    for (const item of Array.isArray(value) ? value : [value]) {
      if (item !== null && item !== undefined && item !== "") search.append(name, String(item));
    }
  }
  const text = search.toString();
  return `/api/v1${path}${text ? `?${text}` : ""}`;
}
