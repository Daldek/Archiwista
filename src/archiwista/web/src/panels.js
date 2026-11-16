/**
 * Side panels of a view (docs/SPEC.md 6.1 „Regulowana szerokość paneli
 * bocznych”), from the mockup: widths by the space the view has, drag
 * handles (WAI-ARIA window splitter) and widths the user set, kept in
 * `localStorage` per view. On a phone (`NARROW`) an open panel is a bottom
 * sheet over the centre.
 */

import { NARROW, useMedia } from "./hooks.js";
import { T, t } from "./labels/index.js";
import { html, Icon, useEffect, useLayoutEffect, useRef, useState } from "./ui.js";

const STORAGE = "archiwista:panel-widths";
/** px: [min, max] width of each side panel. */
const LIMITS = { left: [260, 560], right: [340, 720] };
/** The centre (map, list) keeps at least this width when the panels grow. */
const CENTER_MIN = 480;
const STEP = 16;
const STEP_BIG = 64;

/**
 * Default widths: wide views give the panels more room instead of only
 * widening the centre; the details panel holds one item, so it grows least.
 */
function defaultWidths(width) {
  if (width >= 4300) return { left: 420, right: 560 };
  if (width >= 3100) return { left: 380, right: 500 };
  if (width >= 2300) return { left: 360, right: 460 };
  if (width >= 1600) return { left: 336, right: 420 };
  if (width >= 1200) return { left: 318, right: 380 };
  return { left: 300, right: 380 };
}

const clamp = (value, low, high) => Math.round(Math.min(high, Math.max(low, value)));

function stored(key) {
  try {
    return JSON.parse(localStorage.getItem(key)) ?? {};
  } catch {
    return {};
  }
}

/**
 * Widths of a view's side panels.
 *
 * User widths win over the defaults; when they do not fit, every shown panel
 * shrinks towards its minimum so the centre keeps `CENTER_MIN`.
 *
 * @param {number} width - Width of the whole view in px.
 * @param {{left?: boolean, right?: boolean}} shown - Panels taking a column.
 * @param {string} key - The view, e.g. `map`: its widths are kept apart.
 * @returns {{widths: {left: number, right: number},
 *   range: (side: string) => [number, number],
 *   set: (side: string, width: number) => void,
 *   reset: (side: string) => void}}
 */
export function usePanelWidths(width, shown, key) {
  const storageKey = `${STORAGE}:${key}`;
  const [user, setUser] = useState(() => stored(storageKey));
  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(user));
    } catch {
      // Private mode: the widths last for this page only.
    }
  }, [user]);

  const defaults = defaultWidths(width);
  const sides = Object.keys(LIMITS).filter((side) => shown[side]);
  const widths = {};
  for (const side of Object.keys(LIMITS)) {
    widths[side] = clamp(user[side] ?? defaults[side], ...LIMITS[side]);
  }
  const available = width - CENTER_MIN;
  const total = sides.reduce((sum, side) => sum + widths[side], 0);
  const slack = sides.reduce((sum, side) => sum + widths[side] - LIMITS[side][0], 0);
  if (total > available && slack > 0) {
    const cut = Math.min(1, (total - available) / slack);
    for (const side of sides) {
      widths[side] = Math.round(widths[side] - (widths[side] - LIMITS[side][0]) * cut);
    }
  }
  /** [min, max] of one panel with the other shown panels as they are. */
  const range = (side) => {
    const others = sides.filter((x) => x !== side).reduce((sum, x) => sum + widths[x], 0);
    const [low, high] = LIMITS[side];
    return [low, Math.max(low, Math.min(high, available - others))];
  };
  const set = (side, value) => setUser((u) => ({ ...u, [side]: clamp(value, ...range(side)) }));
  const reset = (side) =>
    setUser((u) => {
      const { [side]: _, ...rest } = u;
      return rest;
    });
  return { widths, range, set, reset };
}

/**
 * Drag handle on the edge of a side panel (WAI-ARIA window splitter): mouse
 * or touch drag, arrows on the focused handle (Shift: bigger step), Home /
 * End = min / max, Enter or double click = default width.
 *
 * @param {object} props
 * @param {string} props.panel - Id of the panel element (`aria-controls`).
 * @param {string} props.label - Name of the panel.
 * @param {number} props.column - Grid column of the panel.
 * @param {"end"|"start"} props.edge - `end`: on the panel's right edge
 *   (dragging right widens it); `start`: on its left edge.
 * @param {number} props.width
 * @param {[number, number]} props.range
 * @param {(width: number) => void} props.onWidth
 * @param {() => void} props.onReset
 */
export function Resizer({ panel, label, column, edge, width, range, onWidth, onReset }) {
  const drag = useRef(null);
  const [min, max] = range;
  const sign = edge === "end" ? 1 : -1;
  const down = (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    event.currentTarget.focus();
    drag.current = { x: event.clientX, width };
    document.body.classList.add("resizing");
  };
  const move = (event) => {
    if (drag.current) onWidth(drag.current.width + sign * (event.clientX - drag.current.x));
  };
  const up = () => {
    drag.current = null;
    document.body.classList.remove("resizing");
  };
  const key = (event) => {
    const step = event.shiftKey ? STEP_BIG : STEP;
    if (event.key === "ArrowRight") onWidth(width + sign * step);
    else if (event.key === "ArrowLeft") onWidth(width - sign * step);
    else if (event.key === "Home") onWidth(min);
    else if (event.key === "End") onWidth(max);
    else if (event.key === "Enter") onReset();
    else return;
    event.preventDefault();
  };
  return html`<div class=${`resizer at-${edge}`} style=${`grid-column:${column}`}
    role="separator" tabindex="0" aria-orientation="vertical"
    aria-label=${t(T.shell.panel.resize, { label })} aria-controls=${panel}
    aria-valuenow=${width} aria-valuemin=${min} aria-valuemax=${max}
    aria-valuetext=${`${width} px`} title=${t(T.shell.panel.resize_title, { label, width })}
    onPointerDown=${down} onPointerMove=${move} onPointerUp=${up} onPointerCancel=${up}
    onLostPointerCapture=${up} onDblClick=${onReset} onKeyDown=${key}></div>`;
}

/**
 * A side panel of `ViewLayout`.
 *
 * @typedef {object} Panel
 * @property {string} label - Its name: the phone sheet's heading, the handle's label.
 * @property {boolean} open - Shown: a column on a computer, a sheet on a phone.
 * @property {() => void} [onClose] - Closes it (the phone sheet's button).
 * @property {*} content
 */

/**
 * A view with side panels around its centre: `left` (e.g. „Wybór”) and
 * `right` (e.g. „Szczegóły”), each with a drag handle on its inner edge.
 * The view decides which panels are open; on a phone they start closed.
 *
 * @param {{id: string, left?: Panel, right?: Panel, children: *}} props - `id`
 *   names the view (the key of its widths); `children` is the centre.
 */
export function ViewLayout({ id, left, right, children }) {
  const narrow = useMedia(NARROW);
  const root = useRef(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    setWidth(root.current.clientWidth);
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(root.current);
    return () => observer.disconnect();
  }, []);
  const shown = { left: !narrow && Boolean(left?.open), right: !narrow && Boolean(right?.open) };
  const panels = usePanelWidths(width, shown, id);
  const style = `--left-w:${shown.left ? panels.widths.left : 0}px;--right-w:${shown.right ? panels.widths.right : 0}px`;
  const handle = (side, spec, column, edge) =>
    html`<${Resizer} panel=${`${id}-${side}`} label=${spec.label} column=${column} edge=${edge}
      width=${panels.widths[side]} range=${panels.range(side)}
      onWidth=${(value) => panels.set(side, value)} onReset=${() => panels.reset(side)} />`;
  const panel = (side, spec) =>
    html`<aside id=${`${id}-${side}`} class=${`view-panel ${side}${spec.open ? " open" : ""}`}
      aria-label=${spec.label}>
      <div class="sheet-head">
        <span class="grip"></span><b>${spec.label}</b>
        ${spec.onClose
          ? html`<button type="button" class="btn ghost icon-btn" onClick=${spec.onClose}
              title=${t(T.shell.panel.close, { label: spec.label })}
              aria-label=${t(T.shell.panel.close, { label: spec.label })}>
              <${Icon} name="x" /></button>`
          : null}
      </div>
      <div class="view-panel-body">${spec.content}</div>
    </aside>`;
  return html`<div class="view-layout" ref=${root} style=${style}>
    ${left ? panel("left", left) : null}
    ${shown.left ? handle("left", left, 1, "end") : null}
    <div class="view-center">${children}</div>
    ${right ? panel("right", right) : null}
    ${shown.right ? handle("right", right, 3, "start") : null}
  </div>`;
}
