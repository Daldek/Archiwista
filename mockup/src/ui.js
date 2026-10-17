// Shared UI pieces: htm binding, icons, coverage and store badges.

import { h } from "preact";
import htm from "htm";
import { coverage, localBadge } from "./labels.js";

export const html = htm.bind(h);

const PATHS = {
  map: "M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2Zm0 0v14m6-12v14",
  stack: "m12 3 9 4.5-9 4.5-9-4.5L12 3Zm-9 9 9 4.5 9-4.5M3 16.5 12 21l9-4.5",
  grid: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  table: "M4 5h16v14H4zM4 10h16M4 15h16M10 5v14",
  chart: "M4 20V4m0 16h16M8 16v-4m4 4V8m4 8v-6",
  chat: "M5 5h14a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1h-8l-5 4v-4H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Z",
  tasks: "M9 6h11M9 12h11M9 18h11M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z",
  merge: "M6 3v6a6 6 0 0 0 6 6h6M18 15l-3-3m3 3-3 3M6 21v-6",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.4-3a7.4 7.4 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 0 0-2-1.2L14.5 3h-5l-.4 2.6a7 7 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a7 7 0 0 0 2 1.2l.4 2.6h5l.4-2.6a7 7 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2Z",
  rect: "M5 6h14v12H5z",
  poly: "m6 18 2-11 8-2 3 8-6 6-7-1Z",
  pin: "M12 21s-7-6.2-7-11a7 7 0 1 1 14 0c0 4.8-7 11-7 11Zm0-8a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z",
  check: "m5 12 5 5 9-10",
  x: "M6 6l12 12M18 6 6 18",
  download: "M12 4v11m0 0-4-4m4 4 4-4M5 20h14",
  copy: "M9 9h10v11H9zM5 15V4h10",
  spark: "M12 3v4m0 10v4M3 12h4m10 0h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6",
  send: "M4 12 20 4l-6 16-3-7-7-1Z",
  eye: "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Zm10 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-11v6m0-9v.5",
  layers: "m12 3 9 4.5-9 4.5-9-4.5L12 3Zm-9 9 9 4.5 9-4.5",
  chevron: "m9 6 6 6-6 6",
  down: "m6 9 6 6 6-6",
  trash: "M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13",
  plus: "M12 5v14M5 12h14",
  file: "M6 3h8l4 4v14H6V3Zm8 0v4h4",
  rotate: "M4 12a8 8 0 0 1 14-5.3M20 4v4h-4M20 12a8 8 0 0 1-14 5.3M4 20v-4h4",
  sidebar: "M4 5h16v14H4zM9 5v14",
};

export function Icon({ name, size = 16, stroke = 1.8, style }) {
  return html`<svg width=${size} height=${size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width=${stroke} stroke-linecap="round" stroke-linejoin="round" style=${style} aria-hidden="true">
    <path d=${PATHS[name]} />
  </svg>`;
}

export function Logo() {
  return html`<div class="brand-mark">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linejoin="round">
      <path d="M4 15.5 12 20l8-4.5M4 11.5 12 16l8-4.5M12 3l8 4.5-8 4.5-8-4.5L12 3Z" />
    </svg>
  </div>`;
}

export function Coverage({ combo, label, lg, short }) {
  const c = label ?? coverage(combo, { short });
  const style = c.kind === "partial" ? `--pct:${Math.max(4, Math.min(96, c.pct))}%` : undefined;
  return html`<span class=${`cov ${c.kind} ${lg ? "lg" : ""}`} style=${style} title=${title(c)}>
    <span class="glyph"></span><span class="cov-t">${c.text}</span>
  </span>`;
}

function title(c) {
  if (c.kind === "full") return "Cały ląd obszaru w pełnych arkuszach jednej kampanii";
  if (c.kind === "multi") return "Komplet dopiero po połączeniu pełnych arkuszy kilku kampanii tego roku";
  if (c.kind === "partial") return "Udział lądu w ramach PEŁNYCH arkuszy (dolna granica)";
  return "Brak kombinacji w aktywnym filtrze";
}

export function Local({ local }) {
  const b = localBadge(local);
  return html`<span class=${`local ${b.kind}`} title="Stan magazynu (symulowany w mockupie)">
    ${b.kind === "some" ? html`<span class="ring" style=${`--p:${Math.round(b.p * 100)}%`}></span>` : null}
    ${b.kind === "done" ? html`<${Icon} name="check" size=${12} stroke=${2.4} />` : null}
    ${b.text}
  </span>`;
}

export function Seg({ options, value, onChange, small }) {
  return html`<div class=${`seg ${small ? "small" : ""}`} role="tablist">
    ${options.map(
      (o) => html`<button class=${o.value === value ? "on" : ""} disabled=${o.disabled}
        title=${o.title} onClick=${() => onChange(o.value)}>
        ${o.icon ? html`<${Icon} name=${o.icon} size=${15} />` : null}${o.label}
      </button>`,
    )}
  </div>`;
}

/** Command block: lines break only between tokens (never inside "--option"). */
export function Cmd({ text }) {
  const copy = () => navigator.clipboard?.writeText(text).catch(() => {});
  const lines = text.split("\n").map((line, i) => html`${i ? html`<br />` : null}${line.split(" ").map((tok, j) => html`${j ? " " : null}<span class="tok">${tok}</span>`)}`);
  return html`<div class="cmd"><code>${lines}</code><button onClick=${copy} title="Kopiuj">kopiuj</button></div>`;
}
