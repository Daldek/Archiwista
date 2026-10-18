/**
 * The one search field of the interface (docs/SPEC.md 6.1 „Jedno pole
 * wyszukiwania”, 6.8 „Wejście”): `Ctrl+K` (`⌘K`) or `/` in any view opens
 * the „Katalog” with its search field focused. The shell's top bar shows the
 * same as a button.
 *
 * The catalog's address is the query of `GET /slots`: `SLOT_PARAMS` are its
 * parameters, so a link of the map — or the map's own filters, carried over
 * by the shortcut — opens the same selection in the catalog.
 */

import { catalog as L } from "./labels/catalog.js";
import { navigate, readRoute } from "./router.js";
import { html, Icon, loadStylesheet, useEffect } from "./ui.js";

/** Parameters of `GET /slots` the catalog keeps in its address, by the API's names. */
export const SLOT_PARAMS = Object.freeze([
  "q",
  "store",
  "product",
  "country",
  "years",
  "unit",
  "location",
  "versions",
  "status",
  "area_id",
  "bbox",
  "bbox_crs",
  "limit",
]);

/** Route id of the catalog view (routes.js). */
export const CATALOG = "catalog";
/** Window event asking the open catalog to focus its search field. */
export const FOCUS_SEARCH = "archiwista:focus-search";

const SHORTCUT_PARAMS = SLOT_PARAMS.filter((name) => !["location", "limit"].includes(name));
let pendingFocus = false;

/**
 * Open the catalog's search: focus the field of an open catalog, else open
 * the catalog with the filters of the current address that it shares (the
 * map's product, area, years…).
 */
export function openSearch() {
  pendingFocus = true;
  const route = readRoute();
  if (route.view === CATALOG) {
    window.dispatchEvent(new Event(FOCUS_SEARCH));
    return;
  }
  const params = {};
  for (const name of SHORTCUT_PARAMS) {
    if (route.params[name]) params[name] = route.params[name];
  }
  navigate(CATALOG, params);
}

/**
 * Whether the catalog should focus its search field (once per request).
 *
 * @returns {boolean}
 */
export function takeSearchFocus() {
  const wanted = pendingFocus;
  pendingFocus = false;
  return wanted;
}

/**
 * The top bar's search button; while it is shown, `Ctrl+K` (`⌘K`) and `/`
 * (outside text fields) open the search from any view.
 */
export function SearchButton() {
  useEffect(() => {
    loadStylesheet(new URL("./search.css", import.meta.url));
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, []);
  return html`<button type="button" class="btn sm search-trigger" onClick=${openSearch}
    title=${L.search.button_title} aria-label=${L.search.label}
    aria-keyshortcuts="Control+K Meta+K /">
    <${Icon} name="search" size=${15} />
    <span class="search-trigger-text">${L.search.button}</span>
    <span class="kbd" aria-hidden="true">${L.search.shortcut}</span>
  </button>`;
}

function shortcut(event) {
  if (event.defaultPrevented || event.altKey) return;
  const modified = event.ctrlKey || event.metaKey;
  const key = event.key ?? "";
  const open =
    (modified && !event.shiftKey && key.toLowerCase() === "k") ||
    (!modified && key === "/" && !typing(event.target));
  if (!open) return;
  event.preventDefault();
  openSearch();
}

/** Whether keys typed into this element are text (a field, a list, an editor). */
function typing(element) {
  if (!(element instanceof Element)) return false;
  if (element.closest("textarea, select, [contenteditable='true'], [contenteditable='']")) {
    return true;
  }
  const input = element.closest("input");
  return input !== null && !["button", "checkbox", "radio", "range", "reset", "submit"].includes(input.type);
}
