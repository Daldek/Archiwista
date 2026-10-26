/**
 * Shared interface pieces: Preact and htm in one import, icons, the
 * technical-value toggle, problems, progress and stylesheets of views.
 *
 * Views import everything from here (`import { html, useState } from
 * "../ui.js"`), not from `vendor/`, so library paths and versions live in one
 * place. Components render through `html` (htm bound to Preact's `h`); texts
 * come from `labels/`.
 */

import htm from "../vendor/htm/htm.mjs";
import { h } from "../vendor/preact/preact.mjs";
import { useState } from "../vendor/preact/hooks.mjs";
import { T, t } from "./labels/index.js";

export {
  Fragment,
  createContext,
  createRef,
  render,
  toChildArray,
} from "../vendor/preact/preact.mjs";
export {
  useCallback,
  useContext,
  useEffect,
  useErrorBoundary,
  useId,
  useLayoutEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "../vendor/preact/hooks.mjs";

/** Tagged template rendering Preact elements: html`<div class="x">${child}</div>`. */
export const html = htm.bind(h);

const ICONS = {
  map: "M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2Zm0 0v14m6-12v14",
  grid: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  table: "M4 5h16v14H4zM4 10h16M4 15h16M10 5v14",
  tasks: "M9 6h11M9 12h11M9 18h11M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z",
  settings:
    "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.4-3a7.4 7.4 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 0 0-2-1.2L14.5 3h-5l-.4 2.6a7 7 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a7 7 0 0 0 2 1.2l.4 2.6h5l.4-2.6a7 7 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2Z",
  rect: "M5 6h14v12H5z",
  poly: "m6 18 2-11 8-2 3 8-6 6-7-1Z",
  pin: "M12 21s-7-6.2-7-11a7 7 0 1 1 14 0c0 4.8-7 11-7 11Zm0-8a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z",
  check: "m5 12 5 5 9-10",
  x: "M6 6l12 12M18 6 6 18",
  copy: "M9 9h10v11H9zM5 15V4h10",
  eye: "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Zm10 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-11v6m0-9v.5",
  alert: "M12 4 2.5 20h19L12 4Zm0 6v4m0 3v.5",
  layers: "m12 3 9 4.5-9 4.5-9-4.5L12 3Zm-9 9 9 4.5 9-4.5",
  chevron: "m9 6 6 6-6 6",
  down: "m6 9 6 6 6-6",
  download: "M12 4v11m-5-5 5 5 5-5M5 20h14",
  trash: "M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13",
  plus: "M12 5v14M5 12h14",
  file: "M6 3h8l4 4v14H6V3Zm8 0v4h4",
  rotate: "M4 12a8 8 0 0 1 14-5.3M20 4v4h-4M20 12a8 8 0 0 1-14 5.3M4 20v-4h4",
  sidebar: "M4 5h16v14H4zM9 5v14",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm5-2 4 4",
  code: "m8 8-4 4 4 4m8-8 4 4-4 4m-2-10-4 12",
  database: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3Zm0 0v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
  fan: "M10 3h9v4h-9zM4 9h13v6H4zM10 17h9v4h-9z",
  chart: "M4 20V4m0 16h16M8 16v-4m4 4V8m4 8v-6",
};

/**
 * A line icon (24 × 24 grid, current text colour).
 *
 * @param {{name: string, size?: number, stroke?: number, className?: string}} props
 *   `name` is a key of the icon set, e.g. `map`, `grid`, `folder`, `settings`.
 */
export function Icon({ name, size = 16, stroke = 1.8, className }) {
  return html`<svg class=${className} width=${size} height=${size} viewBox="0 0 24 24" fill="none"
    stroke="currentColor" stroke-width=${stroke} stroke-linecap="round" stroke-linejoin="round"
    aria-hidden="true" focusable="false"><path d=${ICONS[name]} /></svg>`;
}

/** The Archiwista mark: stacked layers. */
export function Logo() {
  return html`<span class="brand-mark" aria-hidden="true">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"
      stroke-linejoin="round" focusable="false">
      <path d="M4 15.5 12 20l8-4.5M4 11.5 12 16l8-4.5M12 3l8 4.5-8 4.5-8-4.5L12 3Z" />
    </svg>
  </span>`;
}

/**
 * Segmented control: one of a few options.
 *
 * @param {{options: Array<{value: string, label: string, icon?: string,
 *   disabled?: boolean, title?: string}>, value: string,
 *   onChange: (value: string) => void, small?: boolean, label?: string}} props
 */
export function Seg({ options, value, onChange, small, label }) {
  return html`<div class=${small ? "seg small" : "seg"} role="group" aria-label=${label}>
    ${options.map(
      (option) => html`<button type="button" class=${option.value === value ? "on" : ""}
        aria-pressed=${option.value === value ? "true" : "false"} disabled=${option.disabled}
        title=${option.title} onClick=${() => onChange(option.value)}>
        ${option.icon ? html`<${Icon} name=${option.icon} size=${15} />` : null}${option.label}
      </button>`,
    )}
  </div>`;
}

/**
 * A button copying a text to the clipboard, confirming it for a moment.
 *
 * @param {{text: string, label?: string}} props - `label` names what is
 *   copied for screen readers.
 */
export function CopyButton({ text, label }) {
  const [copied, setCopied] = useState(false);
  const copy = () =>
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  const name = copied ? T.common.actions.copied : T.common.actions.copy;
  return html`<button type="button" class="btn ghost sm copy-btn" onClick=${copy}
    title=${name} aria-label=${label ? `${name}: ${label}` : name}>
    <${Icon} name=${copied ? "check" : "copy"} size=${13} />
  </button>`;
}

/**
 * A name for people with its technical value one click away (docs/SPEC.md
 * 6.1 „Przejrzystość”; SPEC 13 v0.1, criterion 6): the segment of a product
 * name, the EPSG code of a system, the path of a version.
 *
 * @param {{children: *, value: string|Array<[string, string]>}} props - The
 *   human name and the technical value, or `[name, value]` pairs.
 */
export function Tech({ children, value }) {
  const [open, setOpen] = useState(false);
  const values = Array.isArray(value) ? value : [[null, value]];
  const action = open ? T.common.technical.hide : T.common.technical.show;
  return html`<span class="tech">
    <span class="tech-label">${children}</span>
    <button type="button" class="tech-toggle" aria-expanded=${open ? "true" : "false"}
      title=${action} aria-label=${action} onClick=${() => setOpen(!open)}>
      <${Icon} name="code" size=${13} />
    </button>
    ${open
      ? html`<span class="tech-values">
          ${values.map(
            ([name, text]) => html`<span class="tech-value">
              ${name ? html`<span class="tech-name">${name}</span>` : null}
              <code>${text}</code><${CopyButton} text=${text} label=${name ?? text} />
            </span>`,
          )}
        </span>`
      : null}
  </span>`;
}

/**
 * A JSON Pointer (`errors[].pointer`) as a dotted path for people:
 * `/query/limit` is `query.limit`.
 *
 * @param {string|undefined} pointer
 * @returns {string}
 */
export function pointerPath(pointer) {
  const parts = String(pointer ?? "").split("/").slice(1);
  return parts.map((part) => part.replaceAll("~1", "/").replaceAll("~0", "~")).join(".");
}

/**
 * A problem of the API (RFC 9457) for people: the Polish title and detail,
 * the fields to fix, the producer's own message, the code a click away.
 *
 * @param {{problem: import("./types.js").Problem, compact?: boolean}} props
 */
export function ProblemView({ problem, compact }) {
  const details = problem.details ?? {};
  const fields = [
    ...(details.problems ?? []).map((item) => item.message),
    ...(problem.errors ?? []).map((item) => `${pointerPath(item.pointer)}: ${item.message}`),
  ];
  const producer = Object.entries(details).find(
    ([, member]) => member && typeof member === "object" && "exception" in member,
  );
  // A fix that the detail already ends with is not said twice.
  const hint = problem.hint && !problem.detail.includes(problem.hint) ? problem.hint : null;
  const technical = [[T.common.technical.code, problem.code]];
  if (details.reason) technical.push([T.common.technical.reason, details.reason]);
  technical.push([T.common.technical.type, problem.type]);
  return html`<div class=${compact ? "problem compact" : "problem"} role="alert">
    <div class="problem-head"><${Icon} name="alert" /><b>${problem.title}</b></div>
    <p class="problem-detail">${problem.detail}</p>
    ${hint ? html`<p class="problem-hint">${hint}</p>` : null}
    ${fields.length
      ? html`<div class="problem-fields">${T.common.problem.fields}
          <ul>${fields.map((text) => html`<li>${text}</li>`)}</ul></div>`
      : null}
    ${producer
      ? html`<p class="problem-producer">${t(T.common.problem.producer, { package: producer[0] })}
          <code>${producer[1].message}</code></p>`
      : null}
    ${details.job
      ? html`<p class="problem-job">${t(T.common.problem.running_job, {
          kind: T.common.job_kind[details.job.kind] ?? details.job.kind,
          state: T.common.job_state[details.job.state] ?? details.job.state,
        })}</p>`
      : null}
    <${Tech} value=${technical}>
      <span class="faint">HTTP ${problem.status || "–"}</span>
    </${Tech}>
  </div>`;
}

/**
 * A spinner with its text for screen readers (and people, unless `quiet`).
 *
 * @param {{label?: string, quiet?: boolean}} props
 */
export function Spinner({ label = T.common.loading, quiet }) {
  return html`<span class="loading" role="status">
    <span class="spinner" aria-hidden="true"></span>
    <span class=${quiet ? "visually-hidden" : ""}>${label}</span>
  </span>`;
}

const sheets = new Map();

/**
 * Add a view's own stylesheet to the page once, e.g.
 * `loadStylesheet(new URL("./map.css", import.meta.url))`.
 *
 * @param {string|URL} href - Same-origin address (the CSP allows only `self`).
 * @returns {Promise<HTMLLinkElement>} Resolves when the stylesheet is applied.
 */
export function loadStylesheet(href) {
  const url = new URL(href, document.baseURI).href;
  if (!sheets.has(url)) {
    const loaded = new Promise((resolve, reject) => {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = url;
      link.addEventListener("load", () => resolve(link));
      link.addEventListener("error", () => {
        sheets.delete(url);
        link.remove();
        reject(new Error(`Stylesheet not loaded: ${url}`));
      });
      document.head.append(link);
    });
    sheets.set(url, loaded);
  }
  return sheets.get(url);
}
