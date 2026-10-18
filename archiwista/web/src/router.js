/**
 * The address as the source of the interface's state (docs/SPEC.md 6.1
 * „Stan w adresie URL”): `/?view=<view>&<parameters>`, where each view keeps
 * its own parameters — the area, the product, filters, the map position and
 * zoom — so a link opens the same view and Back/Forward walk the changes.
 *
 * The server answers every `/?…` with the interface, so the query string is
 * the state; the fragment only ever carries the one-time token, which
 * `api.js` removes before anything else. Parameter values are strings; a
 * view encodes lists itself (e.g. `years=2020-2023`, `bbox=…`).
 */

import { useEffect, useState } from "../vendor/preact/hooks.mjs";
import { html } from "./ui.js";

/**
 * A view and its parameters, as in the address.
 *
 * @typedef {{view: string|null, params: Object<string, string>}} Route
 */

const VIEW = "view";
/** @type {Set<(route: Route) => void>} */
const listeners = new Set();

window.addEventListener("popstate", notify);

/**
 * The route of an address.
 *
 * @param {{search: string}} [address] - Default: the current location.
 * @returns {Route}
 */
export function readRoute(address = location) {
  const params = Object.fromEntries(new URLSearchParams(address.search));
  const view = params[VIEW] || null;
  delete params[VIEW];
  return { view, params };
}

/**
 * The address of a view with parameters; empty values are left out.
 *
 * @param {string|null} view - Route id (`routes.js`); `null` for the start view.
 * @param {Object<string, string|number|null|undefined>} [params]
 * @returns {string} E.g. `/?view=catalog&product=nmt`.
 */
export function href(view, params = {}) {
  const query = new URLSearchParams();
  if (view) query.set(VIEW, view);
  for (const [name, value] of Object.entries(params)) {
    if (name !== VIEW && value !== null && value !== undefined && value !== "") {
      query.set(name, String(value));
    }
  }
  const text = query.toString();
  return text ? `/?${text}` : "/";
}

/**
 * Open a view.
 *
 * @param {string|null} view
 * @param {Object<string, string|number|null|undefined>} [params]
 * @param {{replace?: boolean}} [options] - `replace`: no new history entry.
 */
export function navigate(view, params = {}, { replace = false } = {}) {
  go(href(view, params), replace);
}

/**
 * Change parameters of the current view; `null` removes one.
 *
 * @param {Object<string, string|number|null|undefined>} patch
 * @param {{replace?: boolean}} [options] - `replace: true` for continuous
 *   changes such as moving the map, so they do not flood the history.
 */
export function setParams(patch, { replace = false } = {}) {
  const { view, params } = readRoute();
  go(href(view, { ...params, ...patch }), replace);
}

/**
 * The current route, re-rendering the component when it changes.
 *
 * @returns {Route}
 */
export function useRoute() {
  const [route, setRoute] = useState(readRoute);
  useEffect(() => {
    listeners.add(setRoute);
    setRoute(readRoute());
    return () => listeners.delete(setRoute);
  }, []);
  return route;
}

/**
 * A link inside the interface: a real `<a href>` (new tab, copying the
 * address) that changes the view without reloading the page.
 *
 * @param {{view: string|null, params?: Object<string, *>, replace?: boolean,
 *   children: *}} props - Other props go to the `<a>` element.
 */
export function Link({ view, params, replace, children, ...rest }) {
  const target = href(view, params);
  const click = (event) => {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    go(target, replace);
  };
  return html`<a href=${target} onClick=${click} ...${rest}>${children}</a>`;
}

function go(address, replace) {
  if (address === location.pathname + location.search) return;
  history[replace ? "replaceState" : "pushState"](null, "", address);
  notify();
}

function notify() {
  const route = readRoute();
  for (const listener of [...listeners]) listener(route);
}
