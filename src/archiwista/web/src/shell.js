/**
 * The shell around the views (mockup layout): the top bar with the stores,
 * the downloads in the background and the session — on a team server the
 * account menu (`AccountMenu`) —, the navigation (a rail on a computer, a bar
 * at the bottom of a phone), the index state banner, the current view of the
 * address and the overlays opened over it, and over all of them the plan
 * windows, the list of downloads and their toasts (downloads.js). Views and
 * overlays come from `routes.js`; the first run, without any store, opens the
 * wizard.
 */

import { endSession, endSessionLabel, issueToken, listSessions, readSession } from "./api.js";
import { AppContext, useApp, useAppState } from "./context.js";
import { IndexBanner } from "./banner.js";
import {
  DownloadsIndicator,
  DownloadsPanel,
  DownloadsProvider,
  DownloadToasts,
  PlanWindows,
} from "./downloads.js";
import { stamp } from "./format.js";
import { account as A } from "./labels/account.js";
import { T, t } from "./labels/index.js";
import { Link, navigate, setParams, useRoute } from "./router.js";
import { findView, OVERLAYS, startView, VIEWS } from "./routes.js";
import { SearchButton } from "./search.js";
import {
  CopyButton,
  html,
  Icon,
  Logo,
  Modal,
  ProblemView,
  Spinner,
  Tech,
  useEffect,
  useErrorBoundary,
  useRef,
  useState,
} from "./ui.js";
import { PasswordChange } from "./views/login.js";

const L = T.shell;
const loaded = new Map();
const ACCOUNT_PANEL = "account-panel";
// The browser and the system a `User-Agent` names, the first mark found.
const BROWSERS = [["Edg/", "Edge"], ["OPR/", "Opera"], ["Firefox/", "Firefox"], ["Chrome/", "Chrome"], ["Safari/", "Safari"]];
const SYSTEMS = [["Windows", "Windows"], ["Android", "Android"], ["iPhone", "iOS"], ["iPad", "iOS"], ["Mac OS X", "macOS"], ["Linux", "Linux"]];

/**
 * The interface of a started session.
 *
 * @param {{session: import("./types.js").SessionState,
 *   onSessionChange: (session: import("./types.js").SessionState) => void,
 *   onSignOut: () => void}} props - `onSessionChange`: the session read
 *   again, or a new one after a password change; `onSignOut`: the person
 *   signed out of a team server.
 */
export function Shell({ session, onSessionChange, onSignOut }) {
  const app = useAppState(session);
  const route = useRoute();
  const view = currentView(route, app.settings, app.settingsError);
  const name = view && !view.unknown ? viewName(view.id) : null;

  useEffect(() => {
    document.title = name ? `${name} · ${L.brand}` : L.brand;
  }, [name]);

  const overlays = OVERLAYS.filter((overlay) => route.params[overlay.param]);
  useEffect(() => {
    if (!overlays.length) return undefined;
    const top = overlays[overlays.length - 1];
    const key = (event) => {
      if (event.key === "Escape") setParams({ [top.param]: null });
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [overlays.map((overlay) => overlay.param).join()]);

  let content;
  if (view === null) content = html`<div class="page"><${Spinner} /></div>`;
  else if (view.unknown) content = html`<${UnknownView} id=${view.unknown} />`;
  else content = html`<${ViewHost} key=${view.id} view=${view} route=${route} />`;

  return html`<${AppContext.Provider} value=${app}>
    <${DownloadsProvider} session=${session}>
      <div class="shell">
        <${TopBar} onSessionChange=${onSessionChange} onSignOut=${onSignOut} />
        <${Navigation} current=${view && !view.unknown ? view.id : null} />
        <div class="shell-main">
          <${IndexBanner} view=${view && !view.unknown ? view.id : null} />
          <main class="content" id="content">${content}</main>
        </div>
        ${overlays.map(
          (overlay) => html`<${OverlayHost} key=${overlay.param} overlay=${overlay} route=${route}
            value=${route.params[overlay.param]}
            onClose=${() => setParams({ [overlay.param]: null })} />`,
        )}
        <${PlanWindows} />
        <${DownloadsPanel} />
        <${DownloadToasts} />
      </div>
    </${DownloadsProvider}>
  </${AppContext.Provider}>`;
}

/**
 * The screen without a session: how to open one, with the server's reason.
 *
 * @param {{problem: import("./types.js").Problem, lost?: boolean}} props
 */
export function SessionScreen({ problem, lost }) {
  const retry = problem.details?.reason === "network_error";
  return html`<div class="session-screen">
    <div class="session-card" role="alert">
      <div class="brand"><${Logo} /><span>${L.brand}</span></div>
      <h1>${L.session.title}</h1>
      ${lost ? html`<p>${L.session.lost}</p>` : null}
      <p class="session-detail">${problem.detail}</p>
      <p class="session-instruction">${L.session.instruction}</p>
      <div class="session-command">
        <span class="muted">${L.session.command_label}</span>
        <code>${L.session.command}</code>
        <${CopyButton} text=${L.session.command} label=${L.session.command} />
      </div>
      ${retry
        ? html`<button type="button" class="btn primary" onClick=${() => location.reload()}>
            <${Icon} name="rotate" />${T.common.actions.retry}</button>`
        : null}
    </div>
  </div>`;
}

/** The view of the address; the wizard while no store is configured. */
function currentView(route, settings, settingsError) {
  if (route.view) return findView(route.view) ?? { unknown: route.view };
  if (settings === undefined && settingsError === undefined) return null;
  if (settings && settings.stores.length === 0) return findView("setup") ?? startView();
  return startView();
}

function viewName(id) {
  return L.nav[id] ?? id;
}

function TopBar({ onSessionChange, onSignOut }) {
  const { health, session } = useApp();
  const actor = T.common.actor[session.actor] ?? session.actor;
  return html`<header class="topbar">
    <${Link} class="brand" view=${null}>
      <${Logo} /><span class="brand-name">${L.brand}</span>
    </${Link}>
    ${health ? html`<span class="env-tag">${t(L.version, { version: health.archiwista })}</span>` : null}
    ${health?.stores.length
      ? html`<div class="crumbs" aria-label=${L.stores_label}>
          ${health.stores.map(
            (item) => html`<span class=${`store-chip ${item.state.status}`} key=${item.store}
              title=${t(L.store_title, {
                name: item.name,
                id: item.store,
                status: T.common.store_status[item.state.status] ?? item.state.status,
              })}>
              <span class="dot" aria-hidden="true"></span>
              <${Tech} value=${[["id", item.store], ["kind", item.kind], ["indexed_at", item.state.indexed_at ?? "–"]]}>
                ${item.name}
              </${Tech}>
            </span>`,
          )}
        </div>`
      : null}
    <div class="top-actions">
      <${DownloadsIndicator} />
      <${SearchButton} />
      ${session.team
        ? html`<${AccountMenu} session=${session} onSessionChange=${onSessionChange} onSignOut=${onSignOut} />`
        : html`<span class="session-chip" title=${t(L.session_expires, { expires_at: stamp(session.expires_at) })}>
            <${Tech} value=${session.actor}>${t(L.session_label, { actor })}</${Tech}>
          </span>`}
    </div>
  </header>`;
}

/**
 * The account of a team session (SPEC 6.5 o): its name, roles and groups —
 * the session is read again whenever the menu opens — with „Zmień hasło…”,
 * „Sesje…”, „Token dla agenta…” and „Wyloguj”. The server refuses a password
 * change to a session of the company's proxy and to an agent, and tokens to
 * an agent: those items are left out. `Esc` and a click outside close it.
 */
function AccountMenu({ session, onSessionChange, onSignOut }) {
  const [open, setOpen] = useState(false);
  const [dialog, setDialog] = useState(null);
  const [count, setCount] = useState(null);
  const panel = useRef(null);
  const toggle = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const reading = new AbortController();
    readSession({ signal: reading.signal }).then(onSessionChange, ignore);
    listSessions({ signal: reading.signal }).then((list) => setCount(list.items.length), ignore);
    panel.current.querySelector("button")?.focus();
    const away = (event) => {
      if (!panel.current?.contains(event.target) && !toggle.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    return () => {
      reading.abort();
      document.removeEventListener("pointerdown", away);
    };
  }, [open]);
  const choose = (name) => {
    setOpen(false);
    setDialog(name);
  };
  const closeDialog = () => {
    setDialog(null);
    toggle.current?.focus();
  };
  const signOut = () => endSession().catch(ignore).then(onSignOut);
  const person = session.kind !== "agent";
  const item = (label, onClick) => html`<button type="button" class="account-item" onClick=${onClick}>${label}</button>`;
  return html`<div class="account">
    <button type="button" ref=${toggle} class="btn sm account-toggle" aria-expanded=${open ? "true" : "false"}
      aria-controls=${ACCOUNT_PANEL} aria-label=${t(A.menu.open, { name: session.name })}
      onClick=${() => setOpen(!open)}>
      <span>${session.name}</span><${Icon} name="down" size=${12} />
    </button>
    ${open
      ? html`<div id=${ACCOUNT_PANEL} class="account-panel" ref=${panel}
          onKeyDown=${(event) => {
            if (event.key !== "Escape") return;
            // Esc closes the menu only, not an overlay under it (Shell).
            event.stopPropagation();
            setOpen(false);
            toggle.current?.focus();
          }}>
          <div class="account-who">
            <b>${session.name} · ${session.actor}</b>
            <span class="muted">${accountFacts(session)}</span>
          </div>
          ${person && session.method !== "proxy" ? item(A.menu.change_password, () => choose("password")) : null}
          ${item(count === null ? A.menu.sessions : t(A.menu.sessions_count, { count }), () => choose("sessions"))}
          ${person ? item(A.menu.token, () => choose("token")) : null}
          ${item(A.menu.sign_out, signOut)}
        </div>`
      : null}
    ${dialog === "password"
      ? html`<${PasswordDialog} session=${session} onChanged=${onSessionChange} onClose=${closeDialog} />`
      : null}
    ${dialog === "sessions" ? html`<${SessionsDialog} session=${session} onClose=${closeDialog} />` : null}
    ${dialog === "token" ? html`<${TokenDialog} session=${session} onClose=${closeDialog} />` : null}
  </div>`;
}

/** „zapis do magazynu · grupy: gis”: the roles and groups of a session now. */
function accountFacts(session) {
  const roles = session.roles.map((role) => A.menu.roles[role] ?? role);
  const facts = [roles.length ? roles.join(", ") : A.menu.no_roles];
  if (session.groups.length) facts.push(t(A.menu.groups, { groups: session.groups.join(", ") }));
  if (session.kind === "agent") facts.unshift(A.menu.agent);
  return facts.join(" · ");
}

/** „Zmień hasło…”: the change of the session's password, then its outcome. */
function PasswordDialog({ session, onChanged, onClose }) {
  const [done, setDone] = useState(false);
  const changed = (started) => {
    setDone(true);
    onChanged(started);
  };
  return html`<${Modal} label=${A.change.title} onClose=${onClose}>
    ${done
      ? html`<p role="status">${A.change.done}</p>
          <div class="modal-actions">
            <button type="button" class="btn primary" onClick=${onClose}>${A.sessions.close}</button>
          </div>`
      : html`<${PasswordChange} session=${session} onChanged=${changed} onCancel=${onClose} />`}
  </${Modal}>`;
}

/** „Sesje…”: the live sessions of the account and its agents, each one ended at once. */
function SessionsDialog({ session, onClose }) {
  const [items, setItems] = useState(null);
  const [problem, setProblem] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = () =>
    listSessions().then(
      (list) => setItems(list.items),
      (error) => {
        if (!error.problem) throw error;
        setProblem(error.problem);
      },
    );
  useEffect(() => {
    load();
  }, []);
  const end = async (labels) => {
    setBusy(true);
    setProblem(null);
    try {
      for (const label of labels) await endSessionLabel(label);
    } catch (error) {
      if (!error.problem) throw error;
      setProblem(error.problem);
    }
    await load();
    setBusy(false);
  };
  const others = (items ?? []).filter((item) => !item.current).map((item) => item.label);
  const title = t(A.sessions.title, { account: session.actor });
  return html`<${Modal} label=${title} onClose=${onClose}>
    <h2>${title}</h2>
    ${problem ? html`<${ProblemView} problem=${problem} compact />` : null}
    ${items === null && problem === null ? html`<${Spinner} label=${A.sessions.loading} />` : null}
    ${items
      ? html`<ul class="account-sessions">
          ${items.map(
            (item) => html`<${SessionRow} key=${item.label} item=${item} busy=${busy}
              onEnd=${() => end([item.label])} />`,
          )}
        </ul>`
      : null}
    <div class="modal-actions">
      <button type="button" class="btn" disabled=${busy || others.length === 0} onClick=${() => end(others)}>
        ${A.sessions.end_others}</button>
      <button type="button" class="btn primary" onClick=${onClose}>${A.sessions.close}</button>
    </div>
  </${Modal}>`;
}

/**
 * „przeglądarka · Firefox, Linux · 10.0.0.31 · od …”, or „agent (token) ·
 * 10.0.0.31 · do …”, with „Zakończ” unless it is this session.
 */
function SessionRow({ item, busy, onEnd }) {
  const facts = [item.kind === "agent" ? A.sessions.agent : A.sessions.browser];
  if (item.kind === "browser" && item.user_agent) facts.push(browserName(item.user_agent));
  if (item.client) facts.push(item.client);
  facts.push(
    item.kind === "agent"
      ? t(A.sessions.until, { time: stamp(item.expires_at) })
      : t(A.sessions.since, { time: stamp(item.created_at) }),
  );
  return html`<li class="account-session">
    <span class="account-session-name">${item.current ? A.sessions.current : html`<code>${item.label}</code>`}</span>
    <span class="account-session-facts">${facts.join(" · ")}</span>
    ${item.current
      ? null
      : html`<button type="button" class="btn sm" disabled=${busy}
          aria-label=${t(A.sessions.end_label, { label: item.label })} onClick=${onEnd}>${A.sessions.end}</button>`}
  </li>`;
}

/** „Firefox, Linux” of a `User-Agent`; the text itself when it names neither. */
function browserName(agent) {
  const browser = BROWSERS.find(([mark]) => agent.includes(mark))?.[1];
  const system = SYSTEMS.find(([mark]) => agent.includes(mark))?.[1];
  return browser || system ? [browser, system].filter(Boolean).join(", ") : agent;
}

/** „Token dla agenta…”: a one-time address of an agent's session, shown once. */
function TokenDialog({ session, onClose }) {
  const [issued, setIssued] = useState(null);
  const [problem, setProblem] = useState(null);
  const [busy, setBusy] = useState(false);
  const issue = async () => {
    setBusy(true);
    setProblem(null);
    try {
      setIssued(await issueToken());
    } catch (error) {
      if (!error.problem) throw error;
      setProblem(error.problem);
    }
    setBusy(false);
  };
  return html`<${Modal} label=${A.token.title} onClose=${onClose}>
    <h2>${A.token.title}</h2>
    <p>${t(A.token.intro, { account: session.actor })}</p>
    ${problem ? html`<${ProblemView} problem=${problem} compact />` : null}
    ${issued
      ? html`<div class="account-token">
            <code>${issued.url}</code><${CopyButton} text=${issued.url} label=${A.token.address} />
          </div>
          <p class="field-hint">${t(A.token.shown_once, { time: stamp(issued.expires_at), label: issued.label })}</p>`
      : null}
    <div class="modal-actions">
      ${issued
        ? null
        : html`<button type="button" class="btn primary" disabled=${busy} onClick=${issue}>${A.token.issue}</button>`}
      <button type="button" class="btn" onClick=${onClose}>${A.token.close}</button>
    </div>
  </${Modal}>`;
}

/** A read the account menu does not need: aborted, or refused (the session lost). */
function ignore() {
  return null;
}

function Navigation({ current }) {
  const { session } = useApp();
  const admin = session.roles.includes("admin");
  const shown = (view, bottom) => view.nav !== false && Boolean(view.bottom) === bottom && (admin || !view.admin);
  const items = (bottom) =>
    VIEWS.filter((view) => shown(view, bottom)).map(
      (view) => html`<${Link} key=${view.id} view=${view.id}
        class=${view.id === current ? "rail-item active" : "rail-item"}
        aria-current=${view.id === current ? "page" : null}>
        <${Icon} name=${view.icon} size=${19} /><span>${viewName(view.id)}</span>
        ${view.count ? html`<${RailCount} use=${view.count} />` : null}
      </${Link}>`,
    );
  return html`<nav class="rail" aria-label=${L.nav_label}>
    ${items(false)}
    <span class="rail-spacer"></span>
    ${items(true)}
  </nav>`;
}

/** A view's number next to its name (`ViewRoute.count`), e.g. the running jobs; none at 0. */
function RailCount({ use }) {
  const count = use();
  if (!count) return null;
  return html`<span class="rail-count" aria-hidden="true">${count}</span>
    <span class="visually-hidden">${t(L.nav_count, { count })}</span>`;
}

function ViewHost({ view, route }) {
  const [state, setState] = useState({ module: null, error: null });
  useEffect(() => {
    let live = true;
    load(view).then(
      (module) => live && setState({ module, error: null }),
      (error) => live && setState({ module: null, error }),
    );
    return () => {
      live = false;
    };
  }, [view.id]);
  const name = viewName(view.id);
  if (state.error) {
    return html`<div class="page view-message">
      <p class="hint warn">${t(L.view.failed, { view: name })}</p>
      <code>${String(state.error.message ?? state.error)}</code>
    </div>`;
  }
  if (!state.module) return html`<div class="page"><${Spinner} label=${L.view.loading} /></div>`;
  const Component = state.module.default;
  return html`<${Boundary} name=${name}><${Component} route=${route} /></${Boundary}>`;
}

function OverlayHost({ overlay, route, value, onClose }) {
  const [module, setModule] = useState(null);
  useEffect(() => {
    let live = true;
    load(overlay).then((loadedModule) => live && setModule(loadedModule));
    return () => {
      live = false;
    };
  }, [overlay.param]);
  if (!module) return null;
  const Component = module.default;
  return html`<${Boundary} name=${overlay.param}>
    <${Component} route=${route} value=${value} onClose=${onClose} />
  </${Boundary}>`;
}

/** A view that failed while rendering says so instead of blanking the shell. */
function Boundary({ name, children }) {
  const [error, reset] = useErrorBoundary();
  if (error) {
    return html`<div class="page view-message">
      <p class="hint warn">${t(L.view.crashed, { view: name, message: error.message ?? String(error) })}</p>
      <button type="button" class="btn" onClick=${reset}>${T.common.actions.retry}</button>
    </div>`;
  }
  return children;
}

function UnknownView({ id }) {
  return html`<div class="page view-message">
    <p class="hint warn">${t(L.view.unknown, { view: id })}</p>
    <button type="button" class="btn primary" onClick=${() => navigate(null)}>${L.view.go_start}</button>
  </div>`;
}

/** Import a view or overlay module once; a failed import is tried again later. */
function load(route) {
  const key = route.id ?? route.param;
  if (!loaded.has(key)) {
    loaded.set(
      key,
      route.load().catch((error) => {
        loaded.delete(key);
        throw error;
      }),
    );
  }
  return loaded.get(key);
}
