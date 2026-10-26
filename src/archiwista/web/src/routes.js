/**
 * Views and overlays of the shell (docs/plans/2026-10-18-plan-v0.1.md, WWW contract): a view
 * adds one line to `VIEWS`, an overlay shown over the current view (e.g. the
 * file card, with its own address) one line to `OVERLAYS`. Nothing else in
 * the shell changes.
 *
 * A view: `id` — the `view` parameter of the address and the key of its name
 * in `labels/shell.js` (`nav`); `icon` — an `Icon` name of `ui.js`; `load` —
 * imports the module whose default export is the view component, rendered
 * with `route` (router.js `Route`); `start: true` — the view opened without
 * `view=`; `bottom: true` — placed at the bottom of the navigation; `nav:
 * false` — not in the navigation, opened from another view (e.g. the
 * comparison by „Porównaj z…”); `admin: true` — in the navigation of a
 * session with the role `admin` only (its routes refuse anyone else). The
 * order of the lines is the order of the navigation.
 *
 * An overlay: `param` — the address parameter opening it (`?view=map&file=…`);
 * `load` — imports the module whose default export is rendered with `route`,
 * `value` (the parameter) and `onClose` (removes the parameter; `Esc` too).
 *
 * Example lines:
 *   { id: "map", icon: "map", start: true, load: () => import("./views/map.js") },
 *   { param: "file", load: () => import("./views/file.js") },
 */

/**
 * @typedef {object} ViewRoute
 * @property {string} id
 * @property {string} icon
 * @property {() => Promise<{default: Function}>} load
 * @property {boolean} [start]
 * @property {boolean} [bottom]
 * @property {boolean} [nav]
 * @property {boolean} [admin]
 */

/**
 * @typedef {object} OverlayRoute
 * @property {string} param
 * @property {() => Promise<{default: Function}>} load
 */

/** @type {ViewRoute[]} */
export const VIEWS = [
  { id: "map", icon: "map", start: true, load: () => import("./views/map.js") },
  { id: "catalog", icon: "table", load: () => import("./views/catalog.js") },
  { id: "projects", icon: "folder", load: () => import("./views/projects.js") },
  { id: "store", icon: "database", load: () => import("./views/store.js") },
  { id: "compare", icon: "layers", nav: false, load: () => import("./views/compare.js") },
  { id: "setup", icon: "settings", bottom: true, load: () => import("./setup.js") },
  { id: "accounts", icon: "user", bottom: true, admin: true, load: () => import("./views/accounts.js") },
];

/** @type {OverlayRoute[]} */
export const OVERLAYS = [
  { param: "file", load: () => import("./views/file.js") },
  { param: "own", load: () => import("./views/own.js") },
];

/** The view opened without `view=`: the one marked `start`, else the first. */
export function startView() {
  return VIEWS.find((view) => view.start) ?? VIEWS[0];
}

/**
 * The view of a route id.
 *
 * @param {string} id
 * @returns {ViewRoute|undefined}
 */
export function findView(id) {
  return VIEWS.find((view) => view.id === id);
}
