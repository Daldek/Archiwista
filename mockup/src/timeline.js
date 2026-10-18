// "Oś czasu" (a mode of the catalog): years x variants x coverage; a cell is a variant.

import { html } from "./ui.js";
import { coverage } from "./labels.js";
import { matches, rank } from "./data.js";

const KIND_FILL = { full: "#22c55e", multi: "#14b8a6", partial: "#f59e0b", none: "#e4e7ec" };

/** Cell of a variant: click, Enter or Space selects it (the same selection as a catalog card). */
function Cell({ c, x, y, w, h, sel, onSelect }) {
  const k = coverage(c);
  const title = `${c.year} · ${c.variant} · ${c.horizontal}\n${k.text}`;
  const key = (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    e.preventDefault();
    onSelect(c);
  };
  let body;
  if (k.kind === "partial") {
    const ph = Math.max(2, (h * k.pct) / 100);
    body = html`<rect x=${x} y=${y} width=${w} height=${h} rx="3" fill="#fef3c7" stroke="#fcd34d" stroke-width="0.8" />
      <rect x=${x} y=${y + h - ph} width=${w} height=${ph} rx="2.5" fill=${KIND_FILL.partial} />`;
  } else if (k.kind === "multi") {
    body = html`<rect x=${x} y=${y} width=${w} height=${h} rx="3" fill="#5eead4" />
      <path d=${`M${x} ${y + h} L${x + w} ${y} L${x + w} ${y + h} Z`} fill=${KIND_FILL.multi} />`;
  } else body = html`<rect x=${x} y=${y} width=${w} height=${h} rx="3" fill=${KIND_FILL[k.kind]} />`;
  return html`<g class=${`tl-cell ${sel ? "sel" : ""}`} role="button" tabindex="0" aria-pressed=${sel ? "true" : "false"}
    aria-label=${`${c.year} · ${c.variant} · ${c.horizontal} · ${k.text}`} onClick=${() => onSelect(c)} onKeyDown=${key}>
    <title>${title}</title>
    ${body}
    <rect class="tl-ring" x=${x - 1.5} y=${y - 1.5} width=${w + 3} height=${h + 3} rx="4" fill="none" />
  </g>`;
}

export function Timeline({ combos, groups, filter, selectedYear, selectedId, onSelect, width }) {
  const numeric = combos.filter((c) => typeof c.year === "number").map((c) => c.year);
  const y0 = Math.min(...numeric);
  const y1 = Math.max(...numeric);
  const cols = [];
  for (let y = y0; y <= y1; y++) cols.push(y);
  if (combos.some((c) => c.year === "aktualne")) cols.push("aktualne");
  const rows = [...new Set(combos.map((c) => c.row))].sort((a, b) => {
    const ca = combos.find((c) => c.row === a);
    const cb = combos.find((c) => c.row === b);
    return (ca.resM ?? 1e9) - (cb.resM ?? 1e9);
  });
  // drawn 1:1 (no upscaling of the text): a wider centre gives the years more room
  const W = Math.max(372, Math.min(1400, width));
  const left = 70;
  const cw = (W - left - 2) / cols.length;
  const bandH = 30; // "w filtrze" band: best variant of the year
  const top = bandH + 22;
  const rh = 27;
  const axis = top + rows.length * rh + 6;
  const vcrsY = axis + 20;
  const vcrsYears = new Map();
  for (const c of combos) {
    if (!c.vcrs) continue;
    vcrsYears.set(c.year, new Set([...(vcrsYears.get(c.year) ?? []), c.vcrs]));
  }
  const H = vcrsYears.size ? vcrsY + 26 : axis + 18;
  const byYear = new Map(groups.map((g) => [g.year, g]));
  const x = (i) => left + i * cw;
  const cell = (c, xx, yy, w, h) => html`<${Cell} c=${c} x=${xx} y=${yy} w=${w} h=${h} sel=${c.id === selectedId} onSelect=${onSelect} />`;
  const everyYear = cols.length <= 12;
  return html`<svg class="timeline" viewBox=${`0 0 ${W} ${H}`} style=${`max-width:${W}px`}>
    ${cols.map((year, i) =>
      year === selectedYear
        ? html`<rect x=${x(i) - 1} y="0" width=${cw + 2} height=${axis + 14} rx="4" fill="#eef2ff" stroke="#a5b4fc" />`
        : null,
    )}
    <text x="0" y=${bandH / 2 + 6} font-size="11" fill="#344054" font-weight="700">w filtrze</text>
    ${cols.map((year, i) => {
      const g = byYear.get(year);
      return g?.best
        ? cell(g.best, x(i) + 1.5, 3, cw - 3, bandH - 4)
        : html`<rect x=${x(i) + 1.5} y="3" width=${cw - 3} height=${bandH - 4} rx="3" fill="none" stroke="#d0d5dd" stroke-dasharray="2 2" />`;
    })}
    <text x="0" y=${top - 8} font-size="9.5" fill="#98a2b3" font-weight="600" letter-spacing="0.6">WSZYSTKIE WARIANTY</text>
    <line x1="0" x2=${W} y1=${top - 3} y2=${top - 3} stroke="#e4e7ec" />
    ${rows.map((row, r) => {
      const yy = top + r * rh;
      const inFilter = combos.some((c) => c.row === row && matches(c, filter));
      return html`<g opacity=${inFilter ? 1 : 0.45}>
        <text x="0" y=${yy + rh / 2 + 4} font-size="11.5" fill="#344054">${row}</text>
        ${cols.map((year, i) => {
          const list = combos.filter((c) => c.row === row && c.year === year && (!filter.color || filter.color === "all" || c.color === filter.color || !c.color)).sort(rank);
          return list[0]
            ? cell(list[0], x(i) + 1.5, yy + 3, cw - 3, rh - 6)
            : html`<circle cx=${x(i) + cw / 2} cy=${yy + rh / 2} r="1.3" fill="#d0d5dd" />`;
        })}
      </g>`;
    })}
    ${cols.map((year, i) => {
      const show = everyYear || i % 2 === (cols.length - 1) % 2 || year === "aktualne" || year === selectedYear;
      return show
        ? html`<text x=${x(i) + cw / 2} y=${axis + 8} font-size="10.5" fill=${year === selectedYear ? "#3730a3" : "#667085"}
            font-weight=${year === selectedYear ? 700 : 400} text-anchor="middle">${year === "aktualne" ? "akt." : `’${String(year).slice(2)}`}</text>`
        : null;
    })}
    ${vcrsYears.size
      ? html`<g>
          ${cols.map((year, i) => {
            const set = vcrsYears.get(year);
            if (!set) return null;
            const evrf = set.has("EVRF2007");
            const kron = set.has("KRON86");
            return html`<g>
              ${evrf ? html`<rect x=${x(i) + 0.5} y=${vcrsY} width=${cw - 1} height=${kron ? 3 : 6} fill="#6366f1" />` : null}
              ${kron ? html`<rect x=${x(i) + 0.5} y=${evrf ? vcrsY + 3 : vcrsY} width=${cw - 1} height=${evrf ? 3 : 6} fill="#94a3b8" />` : null}
            </g>`;
          })}
          <text x="0" y=${vcrsY + 6} font-size="10" fill="#667085">wysokości</text>
          <rect x=${left} y=${vcrsY + 14} width="10" height="6" fill="#6366f1" />
          <text x=${left + 14} y=${vcrsY + 20} font-size="10" fill="#667085">EVRF2007</text>
          <rect x=${left + 72} y=${vcrsY + 14} width="10" height="6" fill="#94a3b8" />
          <text x=${left + 86} y=${vcrsY + 20} font-size="10" fill="#667085">KRON86</text>
        </g>`
      : null}
  </svg>
  <div class="tl-legend">
    <span><i class="tl-sw full"></i>pełne</span>
    <span><i class="tl-sw multi"></i>pełne · kilka kampanii</span>
    <span><i class="tl-sw partial"></i>częściowe — słupek = % lądu w pełnych arkuszach</span>
    <span><i class="tl-sw none"></i>brak w filtrze</span>
  </div>
  <div class="tl-note">Pasek „w filtrze”: najlepszy wariant roku w aktywnym filtrze; niżej wszystkie warianty (rozdzielczość, gęstość; formaty plików jednego zestawu to jedna komórka). Komórka to zestaw: kliknięcie albo Enter wybiera go tak jak karta w „Kaflach”.</div>`;
}
