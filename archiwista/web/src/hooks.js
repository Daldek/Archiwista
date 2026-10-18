/**
 * Hooks shared by views: data from the API and media queries.
 */

import { useEffect, useState } from "../vendor/preact/hooks.mjs";

/** Phone layout below this width: panels as bottom sheets, navigation at the bottom. */
export const NARROW = "(max-width: 860px)";

/**
 * Load data for a component; reload when `deps` change or on demand.
 *
 * @template R
 * @param {(signal: AbortSignal) => Promise<R>} load - Reads the data, usually one
 *   `api.js` call given the signal.
 * @param {Array<*>} deps - Values the data depends on.
 * @returns {{data: R|undefined, error: import("./api.js").ApiError|undefined,
 *   loading: boolean, reload: () => void}} The last data stays while reloading
 *   and after a failed reload.
 */
export function useResource(load, deps) {
  const [state, setState] = useState({ data: undefined, error: undefined, loading: true });
  const [round, setRound] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setState((previous) => ({ ...previous, loading: true }));
    load(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setState({ data, error: undefined, loading: false });
      },
      (error) => {
        if (!controller.signal.aborted) {
          setState((previous) => ({ data: previous.data, error, loading: false }));
        }
      },
    );
    return () => controller.abort();
  }, [...deps, round]);
  return { ...state, reload: () => setRound((n) => n + 1) };
}

/**
 * Whether a media query matches, following its changes.
 *
 * @param {string} query - E.g. `NARROW`.
 * @returns {boolean}
 */
export function useMedia(query) {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const list = window.matchMedia(query);
    const change = () => setMatches(list.matches);
    change();
    list.addEventListener("change", change);
    return () => list.removeEventListener("change", change);
  }, [query]);
  return matches;
}
