/**
 * Legend of the map view: what the colours mean — never colour alone, each
 * swatch has its text (docs/SPEC.md 6.1, WCAG) — and the basemap choice.
 * Offline mode says that there is no basemap and why.
 */

import { t } from "../labels/index.js";
import { map as L } from "../labels/map.js";
import { NARROW } from "../hooks.js";
import { html, Icon, useId, useState } from "../ui.js";
import { scaleLabel } from "./sheets.js";
import { NO_BASEMAP } from "./style.js";

/**
 * The legend card.
 *
 * @param {object} props
 * @param {import("../types.js").MapView|undefined} props.view
 * @param {string} props.versions - The versions filter (`current` by default).
 * @param {{on: boolean, system: string, scale: string}} props.grid
 * @param {boolean} props.area - An area is chosen.
 * @param {boolean} props.offline
 * @param {import("../types.js").BasemapSettings[]} props.basemaps
 * @param {import("../types.js").BasemapSettings|null} props.basemap - Shown one.
 * @param {(name: string) => void} props.onBasemap - A basemap name or `NO_BASEMAP`.
 */
export function Legend({ view, versions, grid, area, offline, basemaps, basemap, onBasemap }) {
  const id = useId();
  const [open, setOpen] = useState(() => !window.matchMedia(NARROW).matches);
  const action = open ? L.legend.hide : L.legend.show;
  return html`<section class=${`legend map-legend float-card ${open ? "" : "closed"}`} aria-labelledby=${`${id}-title`}>
    <button type="button" class="legend-title" aria-expanded=${open ? "true" : "false"} aria-controls=${`${id}-rows`}
      title=${action} onClick=${() => setOpen(!open)}>
      <span id=${`${id}-title`}>${L.legend.title}</span><${Icon} name=${open ? "down" : "chevron"} size=${14} />
    </button>
    <div id=${`${id}-rows`} class="legend-rows" hidden=${!open}>
      ${view?.aggregated
        ? html`<div class="legend-row"><span class="sw sw-cells" aria-hidden="true"></span>${L.legend.cells}</div>`
        : html`<div class="legend-row"><span class="sw sw-footprint" aria-hidden="true"></span>
            ${t(L.legend.footprints, { versions: L.filters.versions_options[versions] ?? versions })}</div>`}
      ${area ? html`<div class="legend-row"><span class="sw sw-area" aria-hidden="true"></span>${L.legend.area}</div>` : null}
      ${grid.on
        ? html`<div class="legend-row"><span class="sw sw-sheet" aria-hidden="true"></span>
            ${t(L.legend.sheets, { system: L.area.systems[grid.system] ?? grid.system, scale: scaleLabel(grid.scale) })}</div>`
        : null}
      ${offline
        ? html`<p class="legend-note">${L.legend.offline}</p>`
        : html`<label class="legend-basemap">
            <span>${L.legend.basemap}</span>
            <select value=${basemap?.name ?? NO_BASEMAP} onChange=${(event) => onBasemap(event.currentTarget.value)}>
              ${basemaps.map((item) => html`<option value=${item.name}>${item.name}</option>`)}
              <option value=${NO_BASEMAP}>${L.legend.no_basemap}</option>
            </select>
          </label>`}
    </div>
  </section>`;
}
