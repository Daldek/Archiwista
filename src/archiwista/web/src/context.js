/**
 * State the shell shares with every view: the session, the settings, the
 * session's own preferences and the index state of `GET /health`, refreshed
 * while the shell is open.
 *
 * A view reads it with `useApp()`. The health is polled every 2 s while a
 * store waits for its first scan or a job runs (the wizard and the banner
 * show the progress) and every 15 s otherwise; a view that starts a job
 * calls `refreshHealth()` at once. The preferences (`GET /preferences`: the
 * year types, the basemap, the path aliases) are read once; a view changes
 * them with `savePreferences`, which sends one change after the other, each
 * onto the preferences the last answer gave.
 */

import { getHealth, getPreferences, getSettings, putPreferences } from "./api.js";
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
 * @property {import("./types.js").Preferences|undefined} preferences - The session's
 *   own, as the server last answered them; `undefined` until read.
 * @property {import("./api.js").ApiError|undefined} preferencesError - Why they
 *   could not be read: the views then use the defaults.
 * @property {(change: PreferenceChange) => Promise<import("./types.js").Preferences>}
 *   savePreferences - Replace the preferences with `change` applied (`PUT
 *   /preferences`), a change given as a function getting the preferences of the
 *   last answer; rejects with the server's problem.
 */

/**
 * @typedef {Partial<import("./types.js").Preferences>
 *   | ((current: import("./types.js").Preferences) => Partial<import("./types.js").Preferences>)}
 *   PreferenceChange
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
  const [preferences, setPreferences] = useState();
  const [preferencesError, setPreferencesError] = useState();
  const latestPreferences = useRef();
  const saving = useRef(Promise.resolve());
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
  const keepPreferences = useCallback((answer) => {
    latestPreferences.current = answer;
    setPreferences(answer);
    setPreferencesError(undefined);
    return answer;
  }, []);
  const savePreferences = useCallback((change) => {
    const save = async () => {
      const base = latestPreferences.current ?? (await getPreferences());
      const patch = typeof change === "function" ? change(base) : change;
      return keepPreferences(await putPreferences({ ...base, ...patch }));
    };
    const saved = saving.current.then(save, save);
    saving.current = saved.catch(ignore);
    return saved;
  }, []);

  useEffect(() => {
    refreshSettings();
    // A change waits for the first read, so an older answer never replaces it.
    saving.current = getPreferences().then(keepPreferences, (error) => setPreferencesError(error));
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
      preferences,
      preferencesError,
      savePreferences,
    }),
    [session, health, healthError, settings, settingsError, preferences, preferencesError],
  );
}

/** A failed save the next one does not wait on: its caller has the rejection. */
function ignore() {
  return undefined;
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
