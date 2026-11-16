// Side panels (selection, assistant, "Szczegóły zestawu"): default widths per screen
// width, user widths set with drag handles and kept in localStorage.

import { useEffect, useRef, useState } from "preact/hooks";
import { html } from "./ui.js";

const KEY = "archiwista-mockup:panel-widths";
/** px: [min, max] of the width of each side panel. */
const LIMITS = { left: [260, 560], chat: [300, 760], right: [340, 720] };
const RAIL = 64;
/** The map / fan / catalog keep at least this width when the panels grow. */
const CENTER_MIN = 480;
const STEP = 16;
const STEP_BIG = 64;

/**
 * Default widths: wide screens give the panels more room instead of only widening the map.
 * The details panel holds one set (no year table), so it grows the least.
 */
function defaultWidths(vw) {
  if (vw >= 4400) return { left: 420, chat: 560, right: 560 };
  if (vw >= 3200) return { left: 380, chat: 520, right: 500 };
  if (vw >= 2400) return { left: 360, chat: 440, right: 460 };
  if (vw >= 1700) return { left: 336, chat: 420, right: 420 };
  if (vw >= 1280) return { left: 318, chat: 380, right: 380 };
  return { left: 300, chat: 340, right: 380 };
}

const clamp = (v, lo, hi) => Math.round(Math.min(hi, Math.max(lo, v)));

function stored() {
  try {
    return JSON.parse(localStorage.getItem(KEY)) ?? {};
  } catch {
    return {};
  }
}

export function useViewportWidth() {
  const [vw, setVw] = useState(window.innerWidth);
  useEffect(() => {
    const on = () => setVw(window.innerWidth);
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  return vw;
}

/**
 * Widths of the visible panels (`shown`: which panels take a grid column).
 * User widths win over the defaults; when they do not fit the screen, every
 * panel shrinks towards its minimum so the centre keeps CENTER_MIN.
 */
export function usePanelWidths(vw, shown) {
  const [user, setUser] = useState(stored);
  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(user));
    } catch {
      // private mode: widths live for the session only
    }
  }, [user]);

  const def = defaultWidths(vw);
  const keys = Object.keys(LIMITS).filter((k) => shown[k]);
  const widths = {};
  for (const k of Object.keys(LIMITS)) widths[k] = clamp(user[k] ?? def[k], ...LIMITS[k]);
  const avail = vw - RAIL - CENTER_MIN;
  const total = keys.reduce((s, k) => s + widths[k], 0);
  const slack = keys.reduce((s, k) => s + widths[k] - LIMITS[k][0], 0);
  if (total > avail && slack > 0) {
    const cut = Math.min(1, (total - avail) / slack);
    for (const k of keys) widths[k] = Math.round(widths[k] - (widths[k] - LIMITS[k][0]) * cut);
  }
  /** [min, max] for one panel with the other visible panels as they are now. */
  const range = (k) => {
    const others = keys.filter((x) => x !== k).reduce((s, x) => s + widths[x], 0);
    const [lo, hi] = LIMITS[k];
    return [lo, Math.max(lo, Math.min(hi, avail - others))];
  };
  const set = (k, v) => setUser((u) => ({ ...u, [k]: clamp(v, ...range(k)) }));
  const reset = (k) =>
    setUser((u) => {
      const { [k]: _, ...rest } = u;
      return rest;
    });
  return { widths, range, set, reset };
}

/**
 * Drag handle on the edge of a side panel (WAI-ARIA window splitter):
 * mouse / touch drag, arrows on the focused handle (Shift: bigger step),
 * Home / End = min / max, Enter or double click = default width.
 * `edge`: "end" - the handle is on the panel's right edge (dragging right
 * widens it); "start" - on its left edge.
 */
export function Resizer({ panel, label, column, edge, width, range, onWidth, onReset }) {
  const drag = useRef(null);
  const [min, max] = range;
  const sign = edge === "end" ? 1 : -1;
  const down = (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    e.currentTarget.focus();
    drag.current = { x: e.clientX, w: width };
    document.body.classList.add("resizing");
  };
  const move = (e) => {
    if (drag.current) onWidth(drag.current.w + sign * (e.clientX - drag.current.x));
  };
  const up = () => {
    drag.current = null;
    document.body.classList.remove("resizing");
  };
  const key = (e) => {
    const step = e.shiftKey ? STEP_BIG : STEP;
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") onWidth(width + sign * (e.key === "ArrowRight" ? step : -step));
    else if (e.key === "Home") onWidth(min);
    else if (e.key === "End") onWidth(max);
    else if (e.key === "Enter") onReset();
    else return;
    e.preventDefault();
  };
  return html`<div class=${`resizer at-${edge}`} style=${`grid-column:${column}`} role="separator" tabindex="0"
    aria-orientation="vertical" aria-label=${`Szerokość panelu „${label}”`} aria-controls=${panel}
    aria-valuenow=${width} aria-valuemin=${min} aria-valuemax=${max} aria-valuetext=${`${width} px`}
    title=${`${label}: ${width} px — przeciągnij albo strzałki, dwuklik: szerokość domyślna`}
    onPointerDown=${down} onPointerMove=${move} onPointerUp=${up} onPointerCancel=${up} onLostPointerCapture=${up}
    onDblClick=${onReset} onKeyDown=${key}></div>`;
}
