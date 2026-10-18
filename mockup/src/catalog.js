// "Katalog": every variant (one data set, its file formats as badges) as cards
// (by year), as a list or on the timeline. A card, a row or a timeline cell is
// a set: click, Enter or Space selects it (map, fan and the details panel follow).

import { useState } from "preact/hooks";
import { html, Coverage, Local, Seg, Formats } from "./ui.js";
import { bounds } from "./geo.js";
import { span, day, int, mb, plural } from "./labels.js";
import { matches, ownState } from "./data.js";
import { sheetColor, FULL_COLOR, PARTIAL_COLOR, OWN_COLORS } from "./map.js";
import { Timeline } from "./timeline.js";

function Thumb({ fx, area, combo, product }) {
  const ring2180 =
    product === "own"
      ? extentRing(combo.stats.extent)
      : product === "bdot10k"
        ? extentRing(bounds(combo.units.flatMap((t) => fx.powiaty[t]?.rings.flatMap((r) => r.ring2180) ?? [])))
        : area.ring2180;
  const [x0, y0, x1, y1] = bounds(ring2180);
  const pad = 0.06;
  const w = x1 - x0;
  const h = y1 - y0;
  const vb = `${x0 - w * pad} ${-(y1 + h * pad)} ${w * (1 + 2 * pad)} ${h * (1 + 2 * pad)}`;
  const pt = ([x, y]) => `${x},${-y}`;
  const aoi = area.ring2180.map(pt).join(" ");
  if (product === "own") {
    const { live, added } = ownState(fx.own, combo.stateIndex, combo.prevIndex);
    return html`<svg viewBox=${vb} preserveAspectRatio="xMidYMid meet">
      ${live.map((x) => html`<polyline points=${x.line2180.map(pt).join(" ")} fill="none" stroke=${added.has(x.id) ? OWN_COLORS.added : OWN_COLORS[x.kind]} stroke-width=${w / (added.has(x.id) ? 110 : 220)} />`)}
    </svg>`;
  }
  if (product === "bdot10k") {
    return html`<svg viewBox=${vb} preserveAspectRatio="xMidYMid meet">
      ${combo.units.flatMap((t) =>
        (fx.powiaty[t]?.rings ?? []).map(
          (r) => html`<polygon points=${r.ring2180.map(pt).join(" ")} fill=${combo.unitsPresent.includes(t) ? FULL_COLOR : PARTIAL_COLOR}
            fill-opacity="0.3" stroke=${combo.local?.members?.has(t) ? "#1d4ed8" : "#fff"} stroke-width=${w / 160} />`,
        ),
      )}
      <polygon points=${aoi} fill="none" stroke="#3730a3" stroke-width=${w / 220} />
    </svg>`;
  }
  const codes = [...combo.sheetsFull, ...combo.sheetsPartial];
  return html`<svg viewBox=${vb} preserveAspectRatio="xMidYMid meet">
    ${codes.map((c) => {
      const ring = fx.sheets[c]?.ring2180;
      if (!ring) return null;
      const full = combo.sheetsFull.includes(c);
      const local = combo.local?.members?.has(c);
      return html`<polygon points=${ring.map(pt).join(" ")} fill=${full ? sheetColor(combo, c) : PARTIAL_COLOR}
        fill-opacity=${full ? 0.35 : 0.6} stroke=${local ? "#1d4ed8" : "#fff"} stroke-width=${local ? w / 160 : w / 500} />`;
    })}
    <polygon points=${aoi} fill="none" stroke="#3730a3" stroke-width=${w / 220} />
  </svg>`;
}

function meta(combo, product) {
  if (product === "own") {
    const s = combo.stats;
    return html`<span>${int(s.count)} ${plural(s.count, "obiekt", "obiekty", "obiektów")} · ${int(s.length / 1000)} km · ${kb(s.size)}</span>
      <span>${combo.current ? (combo.changedSince ? `zmieniony od migawki ${day(combo.changedSince.date)}` : "bez zmian od ostatniej migawki") : `${combo.snapshot.author} · ${combo.snapshot.note}`}</span>`;
  }
  if (product === "bdot10k") {
    const units = combo.unitsPresent.length;
    return html`<span>${units}/${combo.units.length} ${plural(combo.units.length, "powiat", "powiaty", "powiatów")} (${combo.units.join(", ")}) · ${mb(combo.sizeBytes)}</span>`;
  }
  const n = combo.sheetsFull.length + combo.sheetsPartial.length;
  const unit = product === "laz" ? plural(n, "kafel", "kafle", "kafli") : plural(n, "arkusz", "arkusze", "arkuszy");
  return html`<span>${combo.horizontal} · ${int(n)} ${unit} (TAK/NIE ${combo.sheetsFull.length}/${combo.sheetsPartial.length})</span>
    <span>nalot <span class="nw">${span(combo.dates)}</span></span>`;
}

/** Box ring (EPSG:2180) of an extent [x0, y0, x1, y1]. */
function extentRing([x0, y0, x1, y1]) {
  return [[x0, y1], [x1, y1], [x1, y0], [x0, y0]];
}

const kb = (bytes) => (bytes < 1e6 ? `${int(bytes / 1024)} KB` : mb(bytes));

const label = (c) => `${c.year} · ${[c.base, c.horizontal].filter(Boolean).join(" · ")}`;

/** Card of a variant: the whole card is the selection button (details, download and file card: right panel). */
function Card({ fx, area, c, product, filter, sel, onSelect }) {
  return html`<button type="button" class=${`card ${matches(c, filter) ? "" : "off"} ${sel ? "sel" : ""}`}
    aria-pressed=${sel ? "true" : "false"} aria-label=${`Zestaw ${label(c)}`} onClick=${() => onSelect(c)}>
    <span class="card-thumb"><${Thumb} fx=${fx} area=${area} combo=${c} product=${product} /></span>
    <span class="card-body">
      <span class="card-title fmt-line">${c.base ? html`<span>${c.base}</span><span class="faint">·</span>` : null}<${Formats} combo=${c} /></span>
      <span class="card-badges"><${Coverage} combo=${c} /><${Local} local=${c.local} /></span>
      <span class="card-meta">${meta(c, product)}</span>
    </span>
  </button>`;
}

export function CatalogView({ fx, area, product, combos, groups, filter, selectedYear, selectedId, onSelect, mode, onMode, width, visible }) {
  const [onlyMatching, setOnlyMatching] = useState(false);
  const own = product === "own";
  const yearKey = (y) => (y === "aktualne" ? 9999 : typeof y === "number" ? y : combos.find((c) => c.year === y)?.yearSort ?? 0);
  const years = [...new Set(combos.map((c) => c.year))].sort((a, b) => yearKey(b) - yearKey(a));
  // own data: the timeline of years does not apply (snapshot dates); cards and the list
  const viewMode = own && mode === "timeline" ? "cards" : mode;
  const shown = combos.filter((c) => !onlyMatching || matches(c, filter));
  const nMatch = combos.filter((c) => matches(c, filter)).length;
  const nFiles = combos.reduce((s, c) => s + c.formats.length, 0);
  const rowKey = (c) => (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    e.preventDefault();
    onSelect(c);
  };

  return html`<div class=${`view catalog-view ${visible ? "" : "hidden"}`}>
    <div class="cat-head">
      <h3>${own ? `Folder danych projektu · ${combos.length} ${plural(combos.length, "wersja", "wersje", "wersji")} pliku` : `Cały zestaw · ${combos.length} ${plural(combos.length, "wariant", "warianty", "wariantów")}`}</h3>
      <span class="muted">${own
        ? html`<code>${fx.own.folder}${fx.own.file}</code> · migawki w <code>${fx.own.folder}.wersje/</code> · kliknij wersję, aby ją wybrać`
        : `${nMatch} w filtrze · ${nFiles} ${plural(nFiles, "kombinacja", "kombinacje", "kombinacji")} raportu (formaty plików) · kliknij zestaw, aby go wybrać`}</span>
      <div style="margin-left:auto;display:flex;gap:8px;align-items:center">
        ${viewMode === "timeline" || own
          ? null
          : html`<label class="muted" style="display:flex;gap:6px;align-items:center;font-size:12px;cursor:pointer">
              <input type="checkbox" checked=${onlyMatching} onChange=${(e) => setOnlyMatching(e.target.checked)} />
              tylko pasujące do filtra
            </label>`}
        <${Seg} small value=${viewMode} onChange=${onMode} options=${[
          { value: "cards", label: "Kafle", icon: "grid" },
          { value: "list", label: "Lista", icon: "table" },
          { value: "timeline", label: "Oś czasu", icon: "chart", disabled: own, title: own ? "Dla migawek pliku — oś wersji w kafelkach i na liście" : undefined },
        ]} />
      </div>
    </div>
    ${viewMode === "timeline"
      ? html`<div class="cat-timeline">
          <${Timeline} combos=${combos} groups=${groups} filter=${filter} selectedYear=${selectedYear} selectedId=${selectedId} onSelect=${onSelect} width=${width - 64} />
        </div>`
      : viewMode === "cards"
      ? html`<div class="cat-years">${years.map((year) => {
          const list = shown.filter((c) => c.year === year);
          if (!list.length) return null;
          return html`<div class="cat-row">
            <div class="cat-year">
              <span class=${`yr ${typeof year === "number" ? "" : own && year !== "bieżący" ? "word date" : "word"}`}>${year}</span>
              <span class="faint" style="font-size:11px">${own ? (list[0].current ? "plik roboczy" : list[0].snapshot.label.split("_")[1]) : `${list.length} ${plural(list.length, "wariant", "warianty", "wariantów")}`}</span>
            </div>
            <div class="cat-grid">
              ${list.map(
                (c) => html`<${Card} key=${c.id} fx=${fx} area=${area} c=${c} product=${product} filter=${filter} sel=${c.id === selectedId} onSelect=${onSelect} />`,
              )}
            </div>
          </div>`;
        })}</div>`
      : html`<div class="cat-list"><table>
          <thead><tr><th>${own ? "Wersja" : "Rok"}</th><th>${own ? "Opis" : "Wariant"}</th><th>${own ? "Stan" : "Pokrycie"}</th><th>${own ? "Obiekty" : product === "bdot10k" ? "Powiaty" : "TAK/NIE"}</th><th>${own || product === "bdot10k" ? "Rozmiar" : "Nalot"}</th><th>${own ? "Miejsce" : "Magazyn"}</th></tr></thead>
          <tbody>
            ${shown.map(
              (c) => html`<tr class=${`${matches(c, filter) ? "" : "off"} ${c.id === selectedId ? "sel" : ""}`} tabindex="0"
                aria-selected=${c.id === selectedId ? "true" : "false"} aria-label=${`Zestaw ${label(c)}`} onClick=${() => onSelect(c)} onKeyDown=${rowKey(c)}>
                <td class="tabular nw" style="font-weight:700">${c.year}</td>
                <td><div class="fmt-line">${c.base ? html`<span>${c.base}</span><span class="faint">·</span>` : null}<${Formats} combo=${c} /></div><div class="faint" style="font-size:11px">${own ? (c.current ? "plik roboczy w dane/" : `${c.snapshot.author} · ${c.snapshot.note}`) : product === "bdot10k" ? "pakiety powiatów" : c.horizontal}</div></td>
                <td><${Coverage} combo=${c} /></td>
                <td class="tabular nw">${own ? int(c.stats.count) : product === "bdot10k" ? `${c.unitsPresent.length}/${c.units.length}` : `${c.sheetsFull.length}/${c.sheetsPartial.length}`}</td>
                <td class="muted tabular nw">${own ? kb(c.stats.size) : product === "bdot10k" ? mb(c.sizeBytes) : span(c.dates)}</td>
                <td><${Local} local=${c.local} /></td>
              </tr>`,
            )}
          </tbody>
        </table></div>`}
  </div>`;
}

export { day };
