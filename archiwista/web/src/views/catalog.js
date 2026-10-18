/**
 * „Katalog” (docs/SPEC.md 6.8; plan v0.1 step 10c): every indexed file of
 * the filters — also the files without an outline, which the map never
 * shows — as a list paged by the cursor of `GET /slots` and drawn only near
 * the view, so the 50 000-slot store stays fast.
 *
 * The address is the query: its parameters are those of `GET /slots`
 * (`search.js` `SLOT_PARAMS`), so a shared link, the map's „bez obrysu”
 * counter (`location=none`) and Back/Forward open the same list. Location
 * groups come with their counts over the whole answer; the search field is
 * the one of `Ctrl+K`. A row opens the file card overlay (`file=`).
 */

import { listSlots } from "../api.js";
import { useApp } from "../context.js";
import { count, int } from "../format.js";
import { NARROW, useMedia } from "../hooks.js";
import { catalog as L } from "../labels/catalog.js";
import { T, t } from "../labels/index.js";
import { ViewLayout } from "../panels.js";
import { href, Link, navigate, setParams } from "../router.js";
import { findView } from "../routes.js";
import { CATALOG, FOCUS_SEARCH, SLOT_PARAMS, takeSearchFocus } from "../search.js";
import {
  html,
  Icon,
  loadStylesheet,
  ProblemView,
  Spinner,
  Tech,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "../ui.js";
import { CatalogFilters, FILTERS } from "./catalog-filters.js";
import { CatalogGrid, onMapOf } from "./catalog-grid.js";

const STYLES = new URL("./catalog.css", import.meta.url);
/** Location groups of `location`, the first one the API's default. */
const GROUPS = ["any", "with", "none"];
/** Filters the map reads (its own names are those of `/slots`). */
const MAP_PARAMS = ["store", "product", "country", "years", "unit", "versions", "status", "q", "area_id"];
/** Rows of a page: the API's maximum, so 50 000 rows take 250 requests. */
const PAGE = 200;
/** Typing pauses this long before the search is sent. */
const TYPING_MS = 300;

/**
 * The `/slots` parameters of an address, by the API's names; others (the
 * file card's `file=`) stay out of the query.
 *
 * @param {Object<string, string>} params
 * @returns {Object<string, string>}
 */
function slotQuery(params) {
  const query = {};
  for (const name of SLOT_PARAMS) {
    if (params[name]) query[name] = params[name];
  }
  return query;
}

/**
 * Rows of the answer in a location group, from `groups`.
 *
 * @param {import("../types.js").LocationGroups|null} groups
 * @param {string} location - `any`, `with` or `none`.
 * @returns {number|null}
 */
function groupTotal(groups, location) {
  if (!groups) return null;
  if (location === "with") return groups.footprint + groups.country;
  if (location === "none") return groups.none;
  return groups.footprint + groups.country + groups.none;
}

/**
 * The catalog view.
 *
 * @param {{route: import("../router.js").Route}} props
 */
export default function Catalog({ route }) {
  const { params } = route;
  const app = useApp();
  const narrow = useMedia(NARROW);
  const [styled, setStyled] = useState(false);
  const [panel, setPanel] = useState(() => !window.matchMedia(NARROW).matches);
  const key = JSON.stringify(slotQuery(params));
  const query = useMemo(() => JSON.parse(key), [key]);
  const pages = usePages(query, key);
  const search = useRef(null);
  const grid = useRef(null);
  const indexStamp = (app.health?.stores ?? [])
    .map((item) => `${item.store}:${item.state.indexed_at}`)
    .join("|");

  useEffect(() => {
    loadStylesheet(STYLES).then(
      () => setStyled(true),
      () => setStyled(true),
    );
    const focus = () => {
      if (takeSearchFocus()) search.current?.focus();
    };
    window.addEventListener(FOCUS_SEARCH, focus);
    return () => window.removeEventListener(FOCUS_SEARCH, focus);
  }, []);
  useEffect(() => {
    if (styled && takeSearchFocus()) search.current?.focus();
  }, [styled]);
  useIndexRefresh(indexStamp, pages);

  if (!styled) return html`<div class="page"><${Spinner} /></div>`;

  const location = GROUPS.includes(query.location) ? query.location : "any";
  const total = groupTotal(pages.groups, location);
  const errors = fieldErrors(pages.error);
  const stores = storeList(app);
  const storeNames = stores.length > 1 ? new Map(stores.map((item) => [item.store, item.name])) : null;
  const map = findView("map") ? (item) => navigate("map", rowMapParams(item, query)) : null;
  const selected = params.file ?? null;
  const cardHref = (item) => href(CATALOG, { ...params, ...cardParams(item, query) });
  const open = (item) => setParams(cardParams(item, query));
  const activeFilters = FILTERS.filter((name) => query[name]);
  const indexing = (app.health?.stores ?? []).some(
    (item) => item.state.status === "unknown" || item.state.running_job?.kind === "scan",
  );

  const filters = html`<${CatalogFilters} query=${query} stores=${stores} errors=${errors}
    indexStamp=${indexStamp} onChange=${(patch) => setParams(patch)}
    onClear=${() => setParams(Object.fromEntries(FILTERS.map((name) => [name, null])))} />`;

  return html`<${ViewLayout} id="catalog"
    left=${{ label: L.filters.label, open: panel, onClose: () => setPanel(false), content: filters }}>
    <section class="cat" aria-label=${L.title}>
      <div class="cat-toolbar">
        <div class="cat-toolbar-row">
          <button type="button" class=${`btn sm${panel ? " active" : ""}`} aria-expanded=${panel ? "true" : "false"}
            aria-controls="catalog-left" title=${L.filters.toggle_title} onClick=${() => setPanel(!panel)}>
            <${Icon} name="sidebar" size=${15} />${L.filters.toggle}
            ${activeFilters.length ? html`<span class="badge-count">${activeFilters.length}</span>` : null}
          </button>
          <${SearchField} value=${query.q ?? ""} inputRef=${search}
            onLeave=${() => grid.current?.focusRow(0)} />
        </div>
        <div class="cat-toolbar-row">
          <${Groups} groups=${pages.groups} location=${location} area=${Boolean(query.area_id || query.bbox)} />
          <span class="cat-spacer"></span>
          <${Summary} total=${total} loaded=${pages.items.length} versions=${query.versions} />
          ${map && location !== "none"
            ? html`<${Link} view="map" params=${pick(query, MAP_PARAMS)} class="btn sm"
                title=${L.result.show_on_map_title}><${Icon} name="map" size=${14} />${L.result.show_on_map}</${Link}>`
            : null}
          <span class="cat-api"><${Tech} value=${[[L.result.api_title, apiAddress(query)]]}>
            <span class="faint">${L.result.api}</span></${Tech}></span>
        </div>
        ${!panel && activeFilters.length
          ? html`<${ActiveFilters} names=${activeFilters} query=${query} stores=${stores} />`
          : null}
        <${Notes} query=${query} location=${location} pages=${pages} />
      </div>
      <div class="cat-body">
        ${pages.error
          ? html`<div class="cat-problem"><${ProblemView} problem=${pages.error.problem} /></div>`
          : html`<${CatalogGrid} items=${pages.items} total=${total} hasMore=${Boolean(pages.next)}
              loading=${pages.loading} loadingMore=${pages.loadingMore} moreError=${pages.moreError}
              onMore=${pages.more} resetKey=${key} narrow=${narrow} handle=${grid}
              isSelected=${(item) => isSelected(item, params)} cardOpen=${Boolean(selected)}
              versions=${query.versions ?? "current"} storeNames=${storeNames}
              cardHref=${cardHref} onOpen=${open} onMap=${map}
              empty=${html`<${Empty} query=${query} indexing=${indexing} activeFilters=${activeFilters}
                location=${location} groups=${pages.groups} />`} />`}
      </div>
      <footer class="cat-foot">
        ${pages.moreError
          ? html`<span class="cat-more-error" role="alert">${L.result.more_failed}
              <button type="button" class="btn sm" onClick=${pages.more}>${T.common.actions.retry}</button></span>`
          : null}
        <span class="cat-keys" id="cat-keys">
          ${L.grid.keys}
          <span class="kbd">↑</span><span class="kbd">↓</span> ${L.grid.key_move} ·
          <span class="kbd">Enter</span> ${L.grid.key_open} ·
          ${map ? html`<span class="kbd">M</span> ${L.grid.key_map} · ` : null}
          <span class="kbd">Ctrl K</span> ${L.grid.key_search}
        </span>
      </footer>
      <div class="visually-hidden" role="status" aria-live="polite">
        ${pages.loading || total === null ? "" : t(L.result.announce, { count: countRows(total, query.versions) })}
      </div>
    </section>
  </${ViewLayout}>`;
}

/**
 * The search field (`q`): sent after a pause in typing; the first change of
 * a typing round adds a history entry, the next ones replace it.
 */
function SearchField({ value, inputRef, onLeave }) {
  const [text, setText] = useState(value);
  const timer = useRef(null);
  const pushed = useRef(false);
  useEffect(() => setText(value), [value]);
  useEffect(() => () => clearTimeout(timer.current), []);
  const commit = (next) => {
    clearTimeout(timer.current);
    const q = next.trim() || null;
    if ((value || null) === q) return;
    setParams({ q }, { replace: pushed.current });
    pushed.current = true;
  };
  const input = (event) => {
    const next = event.currentTarget.value;
    setText(next);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => commit(next), TYPING_MS);
  };
  const keys = (event) => {
    if (event.key === "Enter") {
      commit(text);
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      commit(text);
      onLeave();
    } else if (event.key === "Escape" && text) {
      event.stopPropagation();
      setText("");
      commit("");
    }
  };
  return html`<div class="cat-search" role="search">
    <${Icon} name="search" size=${16} className="cat-search-icon" />
    <input ref=${inputRef} type="search" class="cat-search-input" value=${text}
      aria-label=${L.search.label} aria-describedby="cat-search-hint" aria-keyshortcuts="Control+K /"
      placeholder=${L.search.placeholder} spellcheck="false" autocomplete="off"
      onInput=${input} onKeyDown=${keys}
      onBlur=${() => {
        if (text.trim() !== (value || "")) commit(text);
        pushed.current = false;
      }} />
    <span class="kbd cat-search-kbd" aria-hidden="true">${L.search.shortcut}</span>
    <span id="cat-search-hint" class="visually-hidden">${L.search.hint}</span>
  </div>`;
}

/** The location groups with their counts: a group is the `location` filter. */
function Groups({ groups, location, area }) {
  const G = L.groups;
  const counts = {
    any: groupTotal(groups, "any"),
    with: groupTotal(groups, "with"),
    none: groupTotal(groups, "none"),
  };
  const titles = { any: null, with: G.with_title, none: G.none_title };
  return html`<div class="cat-groups" role="group" aria-label=${G.label}>
    <span class="cat-groups-label">${G.label}:</span>
    ${GROUPS.map(
      (group) => html`<button type="button" key=${group}
        class=${`chip cat-group ${group}${group === location ? " on" : ""}`}
        aria-pressed=${group === location ? "true" : "false"} title=${titles[group]}
        onClick=${() => setParams({ location: group === "any" ? null : group })}>
        ${G[group]}${" "}<span class="cat-count tabular">${counts[group] === null ? "…" : int(counts[group])}</span>
      </button>`,
    )}
    ${groups
      ? html`<span class="faint cat-breakdown">${t(area ? G.breakdown_area : G.breakdown, {
          footprint: int(groups.footprint),
          country: int(groups.country),
        })}</span>`
      : null}
  </div>`;
}

/** The size of the answer and how much of it is loaded. */
function Summary({ total, loaded, versions }) {
  if (total === null) return null;
  return html`<span class="cat-summary">
    <b class="tabular">${countRows(total, versions)}</b>
    ${loaded < total
      ? html`<span class="faint tabular">${t(L.result.loaded, { loaded: int(loaded), total: int(total) })}</span>`
      : null}
  </span>`;
}

/** Active filters as chips while the panel is closed; × removes one. */
function ActiveFilters({ names, query, stores }) {
  return html`<div class="chip-row cat-active" role="group" aria-label=${L.filters.active}>
    ${names.map((name) => {
      const label = L.filters[name] ?? name;
      return html`<button type="button" key=${name} class="chip" onClick=${() => setParams({ [name]: null })}
        title=${t(L.filters.remove, { name: label })} aria-label=${t(L.filters.remove, { name: label })}>
        <span class="muted">${label}:</span> <b>${filterValue(name, query[name], stores)}</b>
        <${Icon} name="x" size=${12} />
      </button>`;
    })}
  </div>`;
}

/** Notes above the list: the exact-unit search, the group without outlines, a changed index. */
function Notes({ query, location, pages }) {
  const unit = exactUnit(query, pages.items);
  if (!unit && location !== "none" && !pages.indexChanged) return null;
  return html`<div class="cat-notes">
    ${unit
      ? html`<button type="button" class="btn sm cat-exact" title=${L.search.exact_unit_title}
          onClick=${() => setParams({ unit, q: null })}>
          <${Icon} name="check" size=${14} />${t(L.search.exact_unit, { unit })}</button>`
      : null}
    ${location === "none"
      ? html`<p class="hint cat-none-note" role="note"><${Icon} name="info" size=${14} /> ${L.groups.none_note}</p>`
      : null}
    ${pages.indexChanged
      ? html`<p class="hint cat-index-note"><${Icon} name="rotate" size=${14} />
          ${L.result.index_changed}
          <button type="button" class="btn sm" onClick=${pages.reload}>${L.result.refresh}</button></p>`
      : null}
  </div>`;
}

/** The empty list: why, and what to change. */
function Empty({ query, indexing, activeFilters, location, groups }) {
  const others = location === "any" ? 0 : groupTotal(groups, "any") ?? 0;
  const text = indexing
    ? L.result.empty_indexing
    : others
      ? t(L.result.empty_group, { group: L.groups[location] })
      : query.unit
        ? t(L.result.empty_unit, { unit: query.unit })
        : L.result.empty;
  return html`<div class="cat-empty-box">
    <p>${text}</p>
    ${others
      ? html`<button type="button" class="btn sm" onClick=${() => setParams({ location: null })}>
          ${t(L.result.show_all, { count: int(others) })}</button>`
      : activeFilters.length
        ? html`<button type="button" class="btn sm"
            onClick=${() => setParams(Object.fromEntries(FILTERS.map((name) => [name, null])))}>
            <${Icon} name="x" size=${14} />${L.filters.clear}</button>`
        : null}
  </div>`;
}

/**
 * Pages of the query: the first one when the query changes, the next ones on
 * demand (`more`), all again on `reload`. Until the first page of a new
 * query arrives, the rows of the previous one stay, marked `loading`.
 */
function usePages(query, key) {
  const [state, setState] = useState({
    key: null,
    items: [],
    next: null,
    groups: null,
    error: null,
    moreError: null,
    loading: true,
    loadingMore: false,
    pages: 0,
    indexChanged: false,
  });
  const run = useRef({ controller: null, busy: false, next: null, loaded: null, query, key });
  run.current.query = query;
  run.current.key = key;

  const fetchPage = (cursor, { quiet = false } = {}) => {
    const live = run.current;
    live.controller?.abort();
    const controller = new AbortController();
    live.controller = controller;
    live.busy = true;
    const first = cursor === null;
    const requested = live.key;
    setState((previous) => ({
      ...previous,
      loading: first && !quiet,
      loadingMore: !first,
      moreError: null,
      error: first ? null : previous.error,
      indexChanged: first ? false : previous.indexChanged,
    }));
    const filters = { limit: PAGE, ...live.query, ...(first ? {} : { cursor }) };
    listSlots(filters, { signal: controller.signal }).then(
      (page) => {
        if (controller.signal.aborted) return;
        live.busy = false;
        live.next = page.next_cursor;
        live.loaded = requested;
        setState((previous) => ({
          ...previous,
          key: requested,
          items: first ? page.items : [...previous.items, ...page.items],
          next: page.next_cursor,
          groups: page.groups,
          error: null,
          moreError: null,
          loading: false,
          loadingMore: false,
          pages: first ? 1 : previous.pages + 1,
        }));
      },
      (error) => {
        if (controller.signal.aborted || error?.name === "AbortError") return;
        live.busy = false;
        if (first) live.loaded = requested;
        setState((previous) =>
          first
            ? { ...previous, key: requested, items: [], next: null, groups: null, error, loading: false, pages: 0 }
            : { ...previous, moreError: error, loadingMore: false },
        );
      },
    );
  };

  useEffect(() => {
    run.current.next = null;
    fetchPage(null);
    return () => run.current.controller?.abort();
  }, [key]);

  return {
    ...state,
    loading: state.loading || state.key !== key,
    more: () => {
      const live = run.current;
      if (!live.busy && live.next && live.loaded === live.key) fetchPage(live.next);
    },
    reload: () => fetchPage(null),
    quietReload: () => fetchPage(null, { quiet: true }),
    markIndexChanged: () => setState((previous) => ({ ...previous, indexChanged: true })),
  };
}

/**
 * Follow the index: after a scan the first page is read again quietly; a
 * list scrolled further gets a note with „Odśwież listę” instead, so the
 * place in it is kept.
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

/** The API's messages by parameter (`errors[].field` is `query.<name>`). */
function fieldErrors(error) {
  const found = {};
  for (const item of error?.problem?.errors ?? []) {
    const name = String(item.field ?? "").replace(/^query\./, "");
    if (name) found[name] = item.message;
  }
  return found;
}

/** A search for exactly a unit code of the rows: offer the exact `unit` filter. */
function exactUnit(query, items) {
  const text = (query.q ?? "").trim();
  if (!text || /\s/.test(text) || query.unit) return null;
  const match = items.find((item) => item.unit && item.unit.toLowerCase() === text.toLowerCase());
  return match ? match.unit : null;
}

function isSelected(item, params) {
  if (params.file !== `${item.store}/${item.slot}`) return false;
  return !params.file_version || params.file_version === item.version?.path;
}

/** The file card of a row: the slot, and the row's version when it is not the current one. */
function cardParams(item, query) {
  const version = query.versions && query.versions !== "current" ? item.version?.path : null;
  return { file: `${item.store}/${item.slot}`, file_version: version ?? null };
}

/** The map of a row with an outline: its unit (or name) in its store and product. */
function rowMapParams(item, query) {
  const params = { store: item.store, product: item.product };
  if (item.unit) params.unit = item.unit;
  else params.q = item.name;
  if (query.versions && query.versions !== "current") params.versions = query.versions;
  return onMapOf(item) ? params : {};
}

function pick(query, names) {
  return Object.fromEntries(names.filter((name) => query[name]).map((name) => [name, query[name]]));
}

function apiAddress(query) {
  const text = new URLSearchParams(query).toString();
  return `/api/v1/slots${text ? `?${text}` : ""}`;
}

function countRows(total, versions) {
  return count(total, versions && versions !== "current" ? L.result.versions : L.result.files);
}

function storeList(app) {
  if (app.health) return app.health.stores.map((item) => ({ store: item.store, name: item.name }));
  return (app.settings?.stores ?? []).map((item) => ({ store: item.id, name: item.name }));
}

function filterValue(name, value, stores) {
  if (name === "versions") return L.versions[value] ?? value;
  if (name === "status") return L.status[value] ?? value;
  if (name === "country") return L.countries[value] ? `${L.countries[value]} (${value})` : value;
  if (name === "store") return stores.find((item) => item.store === value)?.name ?? value;
  return value;
}
