/**
 * Downloads in the background (docs/SPEC.md 5.6, 6.2 „Zadania”, 6.5 f and h;
 * ADR-043): the session's runs that write a store over the network
 * (`download`, `project_download`, `project_repin`) are followed by the
 * shell, so they outlive the plan window, the view and a reload of the page.
 *
 * The shell hosts the plan windows (views/plan.js, `openPlan`), so a window
 * outlives the view that opened it; hidden („Zwiń”) it comes back from the
 * list, closed („Zamknij”) it is gone, and neither cancels anything. Each
 * download started here (`track`), and each queued or running one of the
 * session that `GET /jobs` lists when the page opens or comes back into
 * view, is followed through its event stream; a queued one beyond the second
 * stream waits for its turn in the queue (looked up every 2 s), so the
 * downloads never take the browser's few connections from the map. One that
 * ended meanwhile is read once. The top bar's indicator sums the downloads
 * started together, „Pobieranie 2/6 · 45%” (ended of all, and the mean share
 * of their work: a download of a row's several lines, ADR-044, counts the
 * lines it ran and the units of the one it runs), and opens their list: the
 * progress, the notices, the files, the lines failed or skipped, or why it
 * failed, „Anuluj pobieranie” (the one way to stop a download), „Pokaż okno
 * planu” while its window is kept, and the ended ones
 * until removed. An end shows a toast and tells the `useDownloadEnd`
 * listeners (the map and the step „U źródła” read the store again). This
 * tab's list (ids, names, states) stays in `sessionStorage`, so a reload
 * keeps the names given by plan windows and the downloads that ended.
 */

import { cancelJob, getJob, listJobs, watchJob } from "./api.js";
import { useApp } from "./context.js";
import { int, plural } from "./format.js";
import { downloads as L } from "./labels/downloads.js";
import { t } from "./labels/index.js";
import {
  createContext,
  html,
  Icon,
  loadStylesheet,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "./ui.js";
import {
  downloadSummary,
  FINAL_STATES,
  JobStatus,
  loadCardStyles,
  projectSummary,
  storeName,
} from "./views/cards.js";

/** Kinds of the session's jobs followed here: runs that write a store over the network. */
export const DOWNLOAD_KINDS = new Set(["download", "project_download", "project_repin"]);
const ACTIVE_STATES = ["queued", "running"];
const STORAGE_KEY = "archiwista_downloads";
/** Event streams opened for queued downloads; a running one always gets its own. */
const QUEUED_STREAMS = 2;
const QUEUE_MS = 2000;
const LIST_LIMIT = 200;
const TOAST_MS = 10000;
const TOASTS = 4;
const INDICATOR = "downloads-indicator";
const PANEL = "downloads-panel";

/**
 * A download followed here: the live state of a job (`JobEvents` of
 * views/cards.js) and what the list says of it.
 *
 * @typedef {object} Download
 * @property {string} id
 * @property {string} kind
 * @property {string} title - What it downloads, for people.
 * @property {string|null} store - Store id (`download` only).
 * @property {string} state
 * @property {Object<string, *>|null} progress - The last progress event.
 * @property {Array<{level: string, code: string, message: string}>} notices
 * @property {Object<string, *>|null} result
 * @property {import("./types.js").JobFailure|null} error
 * @property {import("./types.js").Problem|null} stream - It cannot be followed
 *   (e.g. no longer in the index).
 * @property {number} batch - Downloads started while another ran share one.
 * @property {boolean} notified - Its end was told.
 * @property {boolean} cancelling
 * @property {import("./types.js").Problem|null} refused - Why its cancel was refused.
 * @property {number|null} window - The kept plan window that started it.
 * @property {boolean} restored - Read from `sessionStorage`, not yet from the server.
 */

// The context holds the store, which never changes during a session: each
// component that reads the downloads subscribes to it and is drawn again by
// itself, so a download's events never draw the views again. (A provider
// drawing itself again around the shell's children would also break the ids
// of `useId` for what mounts later: Preact counts them per ancestor chain.)
const DownloadsContext = createContext(null);

/**
 * Give the shell's tree the downloads of a session.
 *
 * @param {{session: import("./types.js").SessionState, children: *}} props
 */
export function DownloadsProvider({ session, children }) {
  const store = useMemo(() => createDownloads(session.label), [session.label]);
  useEffect(() => {
    store.start();
    return store.stop;
  }, [store]);
  return html`<${DownloadsContext.Provider} value=${store}>${children}</${DownloadsContext.Provider}>`;
}

/**
 * The downloads of the session, the plan windows, the toasts and what acts on
 * them; the component is drawn again whenever they change.
 */
export function useDownloads() {
  const store = useContext(DownloadsContext);
  const [state, setState] = useState(store.get);
  useEffect(() => {
    setState(store.get());
    return store.subscribe(setState);
  }, [store]);
  return { ...state, ...store.actions };
}

/**
 * What acts on the downloads (`track`, `openPlan`, `cancel`, `onEnd`…), which
 * never changes during a session.
 */
export function useDownloadActions() {
  return useContext(DownloadsContext).actions;
}

/**
 * Call `listener` with each download that ends (any final state, so also a
 * cancelled one, whose finished files are in the store).
 *
 * @param {(item: Download) => void} listener
 */
export function useDownloadEnd(listener) {
  const { onEnd } = useDownloadActions();
  const current = useRef(listener);
  current.current = listener;
  useEffect(() => onEnd((item) => current.current(item)), [onEnd]);
}

/**
 * Whether a download still runs, or waits to: neither ended nor lost.
 *
 * @param {Download|null} item
 * @returns {boolean}
 */
export function downloadActive(item) {
  return Boolean(item) && !FINAL_STATES.has(item.state) && !item.stream;
}

/**
 * The name of a download no plan window named: the producer's command (with
 * the number of its lines when it has several), or the project and its task.
 *
 * @param {import("./types.js").JobDetail} job
 * @param {string|null} [project] - The project's name, else its key.
 * @returns {string}
 */
export function downloadName(job, project = null) {
  const params = job.params ?? {};
  if (job.kind === "download") {
    const calls = params.calls ?? [];
    const values = { producer: params.producer, command: calls[0]?.command ?? "" };
    if (calls.length < 2) return t(L.name.download, values);
    const lines = plural(calls.length, L.name.lines);
    return t(L.name.download_calls, { ...values, count: int(calls.length), lines });
  }
  const name = project ?? params.project;
  const task = job.kind === "project_repin" && params.tasks?.length === 1 ? params.tasks[0] : null;
  return task ? t(L.name.task, { project: name, task }) : t(L.name.project, { project: name });
}

/**
 * The store of a session's downloads, outside Preact: the follow-up of each
 * download, the plan windows, the toasts and whether the list is open.
 *
 * @param {string} label - The session's label: its jobs are `session` = label.
 */
function createDownloads(label) {
  let state = { entries: restore(label), windows: [], toasts: [], panel: false, focus: null };
  let kept = "";
  let timer = null;
  let stopped = false;
  let keys = 0;
  const listeners = new Set();
  const ends = new Set();
  /** @type {Map<string, () => void>} */
  const streams = new Map();

  const emit = () => {
    kept = keep(label, state.entries, kept);
    for (const listener of [...listeners]) listener(state);
  };
  const change = (next) => {
    state = { ...state, ...next(state) };
    emit();
  };
  const entry = (id) => state.entries.find((item) => item.id === id) ?? null;
  const patch = (id, values) =>
    change((now) => ({
      entries: now.entries.map((item) =>
        item.id === id ? { ...item, ...(typeof values === "function" ? values(item) : values) } : item,
      ),
    }));
  const mine = (job) => job.session === label && DOWNLOAD_KINDS.has(job.kind);
  const waiting = () =>
    state.entries.filter((item) => item.state === "queued" && !item.stream && !streams.has(item.id));

  const follow = (id) => {
    if (stopped || streams.has(id)) return;
    streams.set(
      id,
      watchJob(id, {
        onProgress: (data) => patch(id, { progress: data }),
        onNotice: (data) => patch(id, (item) => ({ notices: [...item.notices, data] })),
        onState: (data) => {
          patch(id, { state: data.state, result: data.result ?? null, error: data.error ?? null, restored: false });
          if (FINAL_STATES.has(data.state)) end(id);
        },
        onError: (problem) => {
          streams.delete(id);
          patch(id, { stream: problem, cancelling: false, restored: false });
          promote();
        },
      }),
    );
  };
  // A queued download beyond the streams for queued ones waits for its turn.
  const place = (id) => {
    const item = entry(id);
    if (!item || item.stream || FINAL_STATES.has(item.state) || streams.has(id)) return;
    if (item.state !== "queued" || streams.size < QUEUED_STREAMS) follow(id);
    else schedule();
  };
  const promote = () => {
    for (const item of waiting().reverse()) {
      if (streams.size >= QUEUED_STREAMS) break;
      follow(item.id);
    }
    if (waiting().length) schedule();
  };
  const schedule = () => {
    if (timer === null && !stopped) timer = setTimeout(look, QUEUE_MS);
  };
  // Those of the waiting downloads that left the queue run (or ended): follow them.
  const look = async () => {
    timer = null;
    if (stopped || !waiting().length) return;
    try {
      const queue = await listJobs({ state: "queued", limit: LIST_LIMIT });
      if (stopped) return;
      const still = new Set(queue.items.map((job) => job.id));
      for (const item of waiting()) if (!still.has(item.id)) follow(item.id);
    } catch (error) {
      if (!error.problem) throw error;
    }
    promote();
  };
  // Read once a download that is in neither list: it ended meanwhile.
  const settle = async (id) => {
    try {
      const job = await getJob(id);
      if (stopped || !entry(id)) return;
      patch(id, { state: job.state, progress: job.progress, result: job.result, error: job.error, restored: false });
      if (FINAL_STATES.has(job.state)) end(id);
      else place(id);
    } catch (error) {
      if (!error.problem) throw error;
      if (entry(id)) patch(id, { stream: error.problem, restored: false });
    }
  };
  const end = (id) => {
    streams.delete(id);
    const item = entry(id);
    if (item && !item.notified) {
      patch(id, { notified: true, cancelling: false });
      change((now) => ({ toasts: [...now.toasts, { key: ++keys, id }].slice(-TOASTS) }));
      for (const listener of [...ends]) listener(entry(id));
    } else if (item?.cancelling) {
      patch(id, { cancelling: false });
    }
    promote();
  };
  const add = (job, { title = null, window = null } = {}) => {
    const known = entry(job.id);
    if (known) {
      patch(job.id, { title: title ?? known.title, window: window ?? known.window });
      return;
    }
    const batches = state.entries.map((item) => item.batch);
    const last = Math.max(0, ...batches);
    const batch = state.entries.some(downloadActive) ? last : last + 1;
    const item = fresh(job, title ?? downloadName(job), batch, window);
    change((now) => ({ entries: [item, ...now.entries] }));
    place(job.id);
  };
  // The session's queued and running downloads; those this tab kept are read again.
  const discover = async () => {
    let lists;
    try {
      lists = await Promise.all(ACTIVE_STATES.map((value) => listJobs({ state: value, limit: LIST_LIMIT })));
    } catch (error) {
      if (!error.problem) throw error;
      return;
    }
    if (stopped) return;
    const listed = new Map(
      lists
        .flatMap((list) => list.items)
        .filter(mine)
        .map((job) => [job.id, job]),
    );
    for (const item of state.entries) {
      if (streams.has(item.id) || item.stream) continue;
      const job = listed.get(item.id);
      if (job) {
        patch(item.id, { state: job.state, progress: job.progress, restored: false });
        place(item.id);
      } else if (item.restored || !FINAL_STATES.has(item.state)) {
        settle(item.id);
      }
    }
    const added = [...listed.values()].sort((a, b) => a.created_at.localeCompare(b.created_at));
    for (const job of added) if (!entry(job.id)) add(job);
  };
  const visible = () => {
    if (document.visibilityState === "visible") discover();
  };
  // A window left for another stays only while a download refers to it.
  const leave = (now, shown) =>
    now.windows
      .filter((item) => item.key === shown || now.entries.some((download) => download.window === item.key))
      .map((item) => ({ ...item, visible: item.key === shown }));
  // What the list keeps without some downloads: their windows, toasts and the open list.
  const without = (now, entries) => ({
    entries,
    windows: now.windows.filter((item) => item.visible || entries.some((download) => download.window === item.key)),
    toasts: now.toasts.filter((toast) => entries.some((download) => download.id === toast.id)),
    panel: now.panel && entries.length > 0,
  });

  const actions = {
    /**
     * Follow a job started here when it is a download.
     *
     * @param {import("./types.js").JobDetail} job - The `202` answer.
     * @param {{title?: string|null, window?: number|null}} [options] - Its
     *   name and the plan window that started it.
     */
    track: (job, options) => {
      if (DOWNLOAD_KINDS.has(job.kind) && !stopped) add(job, options);
    },
    /** Ask the server to cancel a download (`POST /jobs/{job}/cancel`). */
    cancel: async (id) => {
      patch(id, { cancelling: true, refused: null });
      try {
        const job = await cancelJob(id);
        if (!FINAL_STATES.has(job.state)) return;
        patch(id, { state: job.state, result: job.result, error: job.error });
        if (!streams.has(id)) end(id);
      } catch (error) {
        if (!error.problem) throw error;
        // One that ended meanwhile says so by its own events.
        const ended = error.problem.details?.reason === "job_finished";
        patch(id, { cancelling: false, refused: ended ? null : error.problem });
        if (ended && !streams.has(id)) settle(id);
      }
    },
    /** Remove an ended download from the list. */
    dismiss: (id) => {
      streams.get(id)?.();
      streams.delete(id);
      change((now) => without(now, now.entries.filter((item) => item.id !== id)));
    },
    /** Remove every ended download from the list. */
    clear: () => change((now) => without(now, now.entries.filter(downloadActive))),
    /**
     * Open a plan window over the shell; another one is hidden while a
     * download refers to it, else closed.
     *
     * @param {Object<string, *>} props - `DownloadPlan`'s props but the window's own.
     */
    openPlan: (props) => {
      const key = ++keys;
      change((now) => ({ windows: [...leave(now, null), { key, props, visible: true }], panel: false }));
    },
    showPlan: (key) => change((now) => ({ windows: leave(now, key), panel: false })),
    hidePlan: (key) =>
      change((now) => ({
        windows: now.windows.map((item) => (item.key === key ? { ...item, visible: false } : item)),
      })),
    closePlan: (key) =>
      change((now) => ({
        windows: now.windows.filter((item) => item.key !== key),
        entries: now.entries.map((item) => (item.window === key ? { ...item, window: null } : item)),
      })),
    /** Show what came of a download: its kept window, else the list at it. */
    show: (id) => {
      const window = entry(id)?.window ?? null;
      if (window !== null && state.windows.some((item) => item.key === window)) actions.showPlan(window);
      else change(() => ({ panel: true, focus: id }));
    },
    setPanel: (open) => change(() => ({ panel: open, focus: null })),
    dropToast: (key) => change((now) => ({ toasts: now.toasts.filter((item) => item.key !== key) })),
    /**
     * @param {(item: Download) => void} listener - Called with each download that ends.
     * @returns {() => void} Stop listening.
     */
    onEnd: (listener) => {
      ends.add(listener);
      return () => ends.delete(listener);
    },
  };

  return {
    get: () => state,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    start: () => {
      discover();
      document.addEventListener("visibilitychange", visible);
    },
    stop: () => {
      stopped = true;
      clearTimeout(timer);
      for (const stop of streams.values()) stop();
      streams.clear();
      document.removeEventListener("visibilitychange", visible);
    },
    actions,
  };
}

/** A download as followed from its `JobDetail`. */
function fresh(job, title, batch, window) {
  return {
    id: job.id,
    kind: job.kind,
    title,
    store: job.store ?? null,
    state: job.state,
    progress: job.progress ?? null,
    notices: [],
    result: job.result ?? null,
    error: job.error ?? null,
    stream: null,
    batch,
    notified: false,
    cancelling: false,
    refused: null,
    window,
    restored: false,
  };
}

/** The downloads this tab kept for the session, as they were last seen. */
function restore(label) {
  let kept = null;
  try {
    kept = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? "null");
  } catch {
    // Not a list this page wrote: start without one.
  }
  if (kept?.label !== label || !Array.isArray(kept.entries)) return [];
  return kept.entries.map((item) => ({
    ...fresh(item, item.title, item.batch, null),
    notified: Boolean(item.notified),
    restored: true,
  }));
}

/** Keep the list for a reload of this tab; answer what was written. */
function keep(label, entries, written) {
  const text = JSON.stringify({
    label,
    entries: entries.map(({ id, kind, title, store, state, batch, notified }) => ({
      id,
      kind,
      title,
      store,
      state,
      batch,
      notified,
    })),
  });
  if (text === written) return written;
  try {
    sessionStorage.setItem(STORAGE_KEY, text);
  } catch {
    // Storage full or off: the list lasts until the page reloads.
  }
  return text;
}

/** The downloads started together, the newest of them: their counts and share done. */
function batchSummary(entries) {
  if (!entries.length) return null;
  const batch = Math.max(...entries.map((item) => item.batch));
  const items = entries.filter((item) => item.batch === batch);
  const running = items.filter(downloadActive).length;
  const share = items.reduce((total, item) => total + part(item), 0) / items.length;
  return {
    total: items.length,
    running,
    done: items.length - running,
    percent: running ? Math.min(99, Math.floor(share * 100)) : 100,
    succeeded: items.filter((item) => item.state === "succeeded").length,
  };
}

/**
 * The share of a download done: of a download of several lines (`call` of
 * `calls`), the lines before the one it runs and that one's share of units.
 */
function part(item) {
  if (!downloadActive(item)) return 1;
  const progress = item.progress;
  if (!progress) return 0;
  const share = progress.total > 0 ? Math.min(1, progress.current / progress.total) : 0;
  if (!(progress.calls > 1)) return share;
  return Math.min(1, ((progress.call ?? 0) + share) / progress.calls);
}

/** Load the styles of the downloads and of the job cards they show. */
function useDownloadStyles() {
  useEffect(() => {
    loadStylesheet(new URL("./downloads.css", import.meta.url));
    loadCardStyles();
  }, []);
}

/**
 * The top bar's „Pobieranie”: the downloads started together, opening their
 * list; nothing while there is none. The text under it for screen readers
 * changes by whole downloads and tens of percent.
 */
export function DownloadsIndicator() {
  const downloads = useDownloads();
  useDownloadStyles();
  const sum = batchSummary(downloads.entries);
  if (!sum) return null;
  const running = sum.running > 0;
  const values = { done: int(sum.done), total: int(sum.total), percent: int(sum.percent), succeeded: int(sum.succeeded) };
  const level = running ? "running" : sum.succeeded === sum.total ? "ok" : "warn";
  const spoken = running
    ? t(L.indicator.running_spoken, { ...values, percent: int(Math.floor(sum.percent / 10) * 10) })
    : t(L.indicator.ended_spoken, values);
  return html`<button type="button" id=${INDICATOR} class=${`btn sm dl-indicator ${level}`}
      aria-expanded=${downloads.panel ? "true" : "false"} aria-controls=${PANEL}
      title=${t(running ? L.indicator.running_title : L.indicator.ended_title, values)}
      onClick=${() => downloads.setPanel(!downloads.panel)}>
      ${running
        ? html`<span class="mini-ring" style=${`--p:${sum.percent}%`} aria-hidden="true"></span>`
        : html`<${Icon} name=${level === "ok" ? "check" : "alert"} size=${14} />`}
      <span>${t(running ? L.indicator.running : L.indicator.ended, values)}</span>
    </button>
    <span class="visually-hidden" role="status">${spoken}</span>`;
}

/** Move the focus to the indicator once it is drawn (a window went there). */
export function focusIndicator() {
  requestAnimationFrame(() => document.getElementById(INDICATOR)?.focus());
}

/**
 * The list of the downloads under the indicator: newest first, each with its
 * progress or result and what can be done with it. `Esc`, its close button
 * and a click outside close it; the focus goes to the indicator.
 */
export function DownloadsPanel() {
  const downloads = useDownloads();
  const { health } = useApp();
  const titleId = useId();
  const box = useRef(null);
  const { panel: open, focus, setPanel } = downloads;
  const close = () => {
    setPanel(false);
    focusIndicator();
  };
  useEffect(() => {
    if (!open) return undefined;
    const target = focus ? box.current.querySelector(`[data-download="${CSS.escape(focus)}"]`) : null;
    (target ?? box.current).focus();
    const away = (event) => {
      const inside = box.current?.contains(event.target) || document.getElementById(INDICATOR)?.contains(event.target);
      if (!inside) setPanel(false);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open, focus]);
  if (!open) return null;
  const ended = downloads.entries.some((item) => !downloadActive(item));
  return html`<section id=${PANEL} class="dl-panel" role="dialog" aria-labelledby=${titleId} tabindex="-1" ref=${box}
    onKeyDown=${(event) => {
      if (event.key !== "Escape") return;
      // Esc closes the list only, not a card under it (shell.js).
      event.stopPropagation();
      close();
    }}>
    <div class="dl-panel-head">
      <h2 class="dl-panel-title" id=${titleId}>${L.panel.title}</h2>
      ${ended ? html`<button type="button" class="btn ghost sm" onClick=${downloads.clear}>${L.panel.clear}</button>` : null}
      <button type="button" class="btn ghost sm icon-btn" aria-label=${L.panel.close} title=${L.panel.close}
        onClick=${close}><${Icon} name="x" size=${14} /></button>
    </div>
    <ul class="dl-list" aria-labelledby=${titleId}>${downloads.entries.map(
      (item) => html`<${DownloadItem} key=${item.id} item=${item}
        store=${item.store ? storeName(health, item.store) : null} />`,
    )}</ul>
  </section>`;
}

function DownloadItem({ item, store }) {
  const downloads = useDownloads();
  const titleId = useId();
  const running = downloadActive(item);
  const kept = item.window !== null && downloads.windows.some((window) => window.key === item.window);
  return html`<li class="dl-item" data-download=${item.id} tabindex="-1" aria-labelledby=${titleId}>
    <p class="dl-item-title" id=${titleId}><b>${item.title}</b>${store ? html`<span class="faint"> · ${store}</span>` : null}</p>
    <${DownloadStatus} item=${item} />
    <div class="dl-item-actions">
      ${running ? html`<${CancelDownload} item=${item} />` : null}
      ${kept
        ? html`<button type="button" class="btn sm" onClick=${() => downloads.showPlan(item.window)}>
            <${Icon} name="eye" size=${13} />${L.item.show_window}</button>`
        : null}
      ${running
        ? null
        : html`<button type="button" class="btn ghost sm" onClick=${() => downloads.dismiss(item.id)}>
            ${L.item.dismiss}</button>`}
    </div>
  </li>`;
}

/**
 * A download's progress, notices and files or why it failed, as the plan
 * window and the list show them (a refused cancel above).
 *
 * @param {{item: Download}} props
 */
export function DownloadStatus({ item }) {
  return html`<${JobStatus} job=${{ events: item, problem: item.refused, kind: item.kind }}
    summary=${item.kind === "download" ? downloadSummary : projectSummary} />`;
}

/**
 * „Anuluj pobieranie”: the explicit stop of a download; closing a window or
 * the list never cancels.
 *
 * @param {{item: Download}} props
 */
export function CancelDownload({ item }) {
  const { cancel } = useDownloadActions();
  return html`<button type="button" class="btn sm" disabled=${item.cancelling} title=${L.item.cancel_title}
    onClick=${() => cancel(item.id)}>
    <${Icon} name="x" size=${13} />${item.cancelling ? L.item.cancelling : L.item.cancel}</button>`;
}

/** The toasts of downloads that ended; each goes after 10 s unless pointed at or focused. */
export function DownloadToasts() {
  const downloads = useDownloads();
  useDownloadStyles();
  return html`<div class="dl-toasts" role="status" aria-label=${L.toast.label}>
    ${downloads.toasts.map((toast) => {
      const item = downloads.entries.find((download) => download.id === toast.id);
      return item ? html`<${Toast} key=${toast.key} toast=${toast} item=${item} />` : null;
    })}
  </div>`;
}

function Toast({ toast, item }) {
  const { dropToast, show } = useDownloadActions();
  const timer = useRef(null);
  const wait = () => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => dropToast(toast.key), TOAST_MS);
  };
  const hold = () => clearTimeout(timer.current);
  useEffect(() => {
    wait();
    return hold;
  }, []);
  const level = item.state === "succeeded" ? "ok" : item.state === "partial" ? "warn" : "bad";
  return html`<div class=${`float-card dl-toast ${level}`}
    onMouseEnter=${hold} onMouseLeave=${wait} onFocusIn=${hold} onFocusOut=${wait}>
    <${Icon} name=${level === "ok" ? "check" : "alert"} size=${16} />
    <span class="dl-toast-text">${t(L.toast[item.state] ?? L.toast.failed, { title: item.title })}</span>
    <button type="button" class="btn sm" onClick=${() => {
      dropToast(toast.key);
      show(item.id);
    }}>${L.toast.show}</button>
    <button type="button" class="btn ghost sm icon-btn" aria-label=${L.toast.close} title=${L.toast.close}
      onClick=${() => dropToast(toast.key)}><${Icon} name="x" size=${14} /></button>
  </div>`;
}

let planModule = null;

/** Import the plan window once; a failed import is tried again by the next window. */
function loadPlan() {
  planModule ??= import("./views/plan.js").catch((error) => {
    planModule = null;
    throw error;
  });
  return planModule;
}

/**
 * The plan windows opened over the shell (`openPlan`); a hidden one keeps
 * its plan and its runs.
 */
export function PlanWindows() {
  const downloads = useDownloads();
  const [module, setModule] = useState(null);
  const count = downloads.windows.length;
  useEffect(() => {
    if (!count || module) return undefined;
    let live = true;
    loadPlan().then(
      (loaded) => live && setModule(loaded),
      () => {
        // The server does not answer: the banner says so, the windows go.
        if (live) for (const item of downloads.windows) downloads.closePlan(item.key);
      },
    );
    return () => {
      live = false;
    };
  }, [count, module]);
  if (!module) return null;
  const { DownloadPlan } = module;
  return downloads.windows.map(
    (item) => html`<${DownloadPlan} key=${item.key} windowKey=${item.key} visible=${item.visible} ...${item.props}
      onMinimise=${() => {
        downloads.hidePlan(item.key);
        focusIndicator();
      }}
      onClose=${() => {
        const handed = downloads.entries.some((download) => download.window === item.key);
        downloads.closePlan(item.key);
        if (handed) focusIndicator();
      }} />`,
  );
}
