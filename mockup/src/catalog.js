// "Katalog": the whole set of combinations as cards (by year) or as a list.

import { useState } from "preact/hooks";
import { html, Coverage, Local, Icon, Seg } from "./ui.js";
import { bounds } from "./geo.js";
import { span, day, int, mb, plural } from "./labels.js";
import { matches } from "./data.js";
import { sheetColor, FULL_COLOR, PARTIAL_COLOR } from "./map.js";

function Thumb({ fx, area, combo, product }) {
  const [x0, y0, x1, y1] = bounds(area.ring2180);
  const pad = 0.06;
  const w = x1 - x0;
  const h = y1 - y0;
  const vb = `${x0 - w * pad} ${-(y1 + h * pad)} ${w * (1 + 2 * pad)} ${h * (1 + 2 * pad)}`;
  const pt = ([x, y]) => `${x},${-y}`;
  const aoi = area.ring2180.map(pt).join(" ");
  if (product === "bdot10k") {
    return html`<svg viewBox=${vb} preserveAspectRatio="xMidYMid meet">
      <polygon points=${aoi} fill=${combo.complete ? FULL_COLOR : PARTIAL_COLOR} fill-opacity="0.25" stroke="#3730a3" stroke-width=${w / 200} />
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
  if (product === "bdot10k") {
    const units = combo.unitsPresent.length;
    return `${units}/${combo.units.length} ${plural(combo.units.length, "powiat", "powiaty", "powiatów")} (${combo.units.join(", ")}) · ${mb(combo.sizeBytes)}`;
  }
  const n = combo.sheetsFull.length + combo.sheetsPartial.length;
  const unit = product === "laz" ? plural(n, "kafel", "kafle", "kafli") : plural(n, "arkusz", "arkusze", "arkuszy");
  const camp = combo.campaignsSelected.length ? combo.campaignsSelected.join(", ") : "–";
  return `${combo.horizontal} · ${int(n)} ${unit} (TAK/NIE ${combo.sheetsFull.length}/${combo.sheetsPartial.length}) · nalot ${span(combo.dates)} · ${camp}`;
}

export function CatalogView({ fx, area, product, combos, filter, selectedYear, onSelectYear, onOpen, onAsk, visible }) {
  const [mode, setMode] = useState("cards");
  const [onlyMatching, setOnlyMatching] = useState(false);
  const yearKey = (y) => (y === "aktualne" ? 9999 : y);
  const years = [...new Set(combos.map((c) => c.year))].sort((a, b) => yearKey(b) - yearKey(a));
  const shown = combos.filter((c) => !onlyMatching || matches(c, filter));
  const nMatch = combos.filter((c) => matches(c, filter)).length;

  return html`<div class=${`view catalog-view ${visible ? "" : "hidden"}`}>
    <div class="cat-head">
      <h3>Cały zestaw · ${combos.length} ${plural(combos.length, "kombinacja", "kombinacje", "kombinacji")}</h3>
      <span class="muted">${nMatch} w filtrze · ${years.length} ${plural(years.length, "rok", "lata", "lat")}</span>
      <div style="margin-left:auto;display:flex;gap:8px;align-items:center">
        <label class="muted" style="display:flex;gap:6px;align-items:center;font-size:12px;cursor:pointer">
          <input type="checkbox" checked=${onlyMatching} onChange=${(e) => setOnlyMatching(e.target.checked)} />
          tylko pasujące do filtra
        </label>
        <${Seg} small value=${mode} onChange=${setMode} options=${[
          { value: "cards", label: "Kafle", icon: "grid" },
          { value: "list", label: "Lista", icon: "table" },
        ]} />
      </div>
    </div>
    ${mode === "cards"
      ? years.map((year) => {
          const list = shown.filter((c) => c.year === year);
          if (!list.length) return null;
          return html`<div class="cat-row">
            <div class="cat-year">
              <span class="yr">${year}</span>
              <span class="faint" style="font-size:11px">${list.length} ${plural(list.length, "wariant", "warianty", "wariantów")}</span>
            </div>
            <div class="cat-grid">
              ${list.map(
                (c) => html`<div class=${`card ${matches(c, filter) ? "" : "off"} ${c.year === selectedYear ? "sel" : ""}`}>
                  <div class="card-thumb" onClick=${() => onSelectYear(c.year)} title="Wybierz rok">
                    <${Thumb} fx=${fx} area=${area} combo=${c} product=${product} />
                  </div>
                  <div class="card-body">
                    <div class="card-title">${c.variant}</div>
                    <div style="display:flex;gap:5px;flex-wrap:wrap"><${Coverage} combo=${c} /><${Local} local=${c.local} /></div>
                    <div class="card-meta">${meta(c, product)}</div>
                    <div class="card-actions">
                      <button class="btn sm" onClick=${() => onOpen(c)}><${Icon} name="file" size=${13} />Karta</button>
                      <button class="btn sm" disabled=${!c.hints.length} onClick=${() => onAsk(c)}
                        title=${c.hints.length ? "" : "Kartograf nie pobiera tego wariantu (brak podpowiedzi pobrania)"}>
                        <${Icon} name="download" size=${13} />Pobierz</button>
                      <button class="btn sm ghost" onClick=${() => onSelectYear(c.year, "map")}><${Icon} name="map" size=${13} />Mapa</button>
                    </div>
                  </div>
                </div>`,
              )}
            </div>
          </div>`;
        })
      : html`<div class="cat-list"><table>
          <thead><tr><th>Rok</th><th>Wariant</th><th>Układ</th><th>Pokrycie</th><th>Arkusze</th><th>Nalot</th><th>Magazyn</th><th></th></tr></thead>
          <tbody>
            ${shown.map(
              (c) => html`<tr class=${matches(c, filter) ? "" : "off"}>
                <td class="tabular" style="font-weight:700">${c.year}</td>
                <td>${c.variant}</td>
                <td class="muted">${c.horizontal}</td>
                <td><${Coverage} combo=${c} /></td>
                <td class="tabular">${product === "bdot10k" ? `${c.unitsPresent.length}/${c.units.length}` : `${c.sheetsFull.length}/${c.sheetsPartial.length}`}</td>
                <td class="muted tabular">${product === "bdot10k" ? "–" : span(c.dates)}</td>
                <td><${Local} local=${c.local} /></td>
                <td><button class="btn sm ghost" onClick=${() => onOpen(c)}>Karta</button></td>
              </tr>`,
            )}
          </tbody>
        </table></div>`}
  </div>`;
}

export { day };
