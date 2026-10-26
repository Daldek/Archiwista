/**
 * The shell around the views (mockup layout): the top bar with the stores,
 * the downloads in the background and the session, the navigation (a rail on
 * a computer, a bar at the bottom of a phone), the index state banner, the
 * current view of the address and the overlays opened over it, and over all
 * of them the plan windows, the list of downloads and their toasts
 * (downloads.js). Views and overlays come from `routes.js`; the first run,
 * without any store, opens the wizard.
 */

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
import { T, t } from "./labels/index.js";
import { Link, navigate, setParams, useRoute } from "./router.js";
import { findView, OVERLAYS, startView, VIEWS } from "./routes.js";
import { SearchButton } from "./search.js";
import {
  CopyButton,
  html,
  Icon,
  Logo,
  Spinner,
  Tech,
  useEffect,
  useErrorBoundary,
  useState,
} from "./ui.js";

const L = T.shell;
const loaded = new Map();

/**
 * The interface of a started session.
 *
 * @param {{session: import("./types.js").SessionState}} props
 */
export function Shell({ session }) {
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
        <${TopBar} />
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

function TopBar() {
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
      <span class="session-chip" title=${t(L.session_expires, { expires_at: stamp(session.expires_at) })}>
        <${Tech} value=${session.actor}>${t(L.session_label, { actor })}</${Tech}>
      </span>
    </div>
  </header>`;
}

function Navigation({ current }) {
  const items = (bottom) =>
    VIEWS.filter((view) => view.nav !== false && Boolean(view.bottom) === bottom).map(
      (view) => html`<${Link} key=${view.id} view=${view.id}
        class=${view.id === current ? "rail-item active" : "rail-item"}
        aria-current=${view.id === current ? "page" : null}>
        <${Icon} name=${view.icon} size=${19} /><span>${viewName(view.id)}</span>
      </${Link}>`,
    );
  return html`<nav class="rail" aria-label=${L.nav_label}>
    ${items(false)}
    <span class="rail-spacer"></span>
    ${items(true)}
  </nav>`;
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
