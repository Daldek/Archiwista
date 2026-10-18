/**
 * State the shell shares with every view: the session, the settings and the
 * index state of `GET /health`, refreshed while the shell is open.
 *
 * A view reads it with `useApp()`. The health is polled every 2 s while a
 * store waits for its first scan or a job runs (the wizard and the banner
 * show the progress) and every 15 s otherwise; a view that starts a job
 * calls `refreshHealth()` at once.
 */

import { getHealth, getSettings } from "./api.js";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "./ui.js";

/**
 * @typedef {object} App
 * @property {import("./types.js").SessionState} session
 * @property {import("./types.js").Health|undefined} health - The last answer.
 * @property {import("./api.js").ApiError|undefined} healthError - Why the last
 *   refresh failed (e.g. the server stopped); cleared by the next answer.
 * @property {import("./types.js").Settings|undefined} settings
 * @property {import("./api.js").ApiError|undefined} settingsError
 * @property {() => Promise<void>} refreshHealth
 * @property {() => Promise<void>} refreshSettings
 * @property {(settings: import("./types.js").Settings) => void} setSettings - The
 *   settings `PUT /settings` answered with.
 */

export const AppContext = createContext(/** @type {App|null} */ (null));

const BUSY_MS = 2000;
const IDLE_MS = 15000;

/**
 * The shared state of the shell.
 *
 * @returns {App}
 */
export function useApp() {
  return useContext(AppContext);
}

/**
 * Create the shared state for a session (the shell calls it once).
 *
 * @param {import("./types.js").SessionState} session
 * @returns {App}
 */
export function useAppState(session) {
  const [health, setHealth] = useState();
  const [healthError, setHealthError] = useState();
  const [settings, setSettings] = useState();
  const [settingsError, setSettingsError] = useState();
  const busy = useRef(true);
  busy.current = health === undefined || health.stores.some(needsWatching);

  const refreshHealth = useCallback(
    () =>
      getHealth().then(
        (answer) => {
          setHealth(answer);
          setHealthError(undefined);
        },
        (error) => setHealthError(error),
      ),
    [],
  );
  const refreshSettings = useCallback(
    () =>
      getSettings().then(
        (answer) => {
          setSettings(answer);
          setSettingsError(undefined);
        },
        (error) => setSettingsError(error),
      ),
    [],
  );

  useEffect(() => {
    refreshSettings();
  }, []);

  useEffect(() => {
    let timer;
    let stopped = false;
    const tick = async () => {
      await refreshHealth();
      if (!stopped) timer = setTimeout(tick, busy.current ? BUSY_MS : IDLE_MS);
    };
    const visible = () => {
      if (document.visibilityState === "visible") refreshHealth();
    };
    tick();
    document.addEventListener("visibilitychange", visible);
    return () => {
      stopped = true;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, []);

  return useMemo(
    () => ({
      session,
      health,
      healthError,
      settings,
      settingsError,
      refreshHealth,
      refreshSettings,
      setSettings,
    }),
    [session, health, healthError, settings, settingsError],
  );
}

/**
 * Whether a store's state changes soon: a job runs or its first scan waits.
 *
 * @param {import("./types.js").StoreItem} item
 * @returns {boolean}
 */
export function needsWatching(item) {
  return item.state.running_job !== null || item.state.status === "unknown";
}
