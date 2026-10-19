/**
 * The switch of the centre „Mapa / Wachlarz / Katalog” (docs/SPEC.md 6.1;
 * plan v0.2 step 13a) and the state the map and the catalog share.
 *
 * The map view shows the map or the Wachlarz of the area's layers
 * (`mode=fan`); „Katalog” is the catalog view itself (`view=catalog`), its
 * timeline `layout=timeline`. Switching keeps the whole address — the
 * filters, the area, the chosen layer (`layer`) and its grouping (`group`),
 * the catalog's layout, the map's position — so going back restores each and
 * a link opens the same. Where the centre has `SPLIT_MIN` px or more, the
 * Wachlarz and the catalog stand beside the map instead of replacing it.
 */

import { map as L } from "../labels/map.js";
import { navigate, setParams } from "../router.js";
import { html, Seg } from "../ui.js";

/** Address parameter of the map view's centre: `FAN_MODE` for the Wachlarz. */
export const MODE_PARAM = "mode";
export const FAN_MODE = "fan";
/** Address parameter of the catalog's layout: `TIMELINE_LAYOUT` for the Oś czasu. */
export const LAYOUT_PARAM = "layout";
export const TIMELINE_LAYOUT = "timeline";
/** Width of the centre in px from which the Wachlarz and the catalog stand beside the map. */
export const SPLIT_MIN = 2000;

/**
 * The switch: a segmented control over the centre of the map and the catalog.
 *
 * @param {{current: "map"|"fan"|"catalog", params: Object<string, string>}}
 *   props - `params`: the address's parameters, carried to the other view.
 */
export function ViewSwitch({ current, params }) {
  const choose = (choice) => {
    if (choice === current) return;
    const mode = choice === "fan" ? FAN_MODE : null;
    if (choice === "catalog") navigate("catalog", { ...params, [MODE_PARAM]: null });
    else if (current === "catalog") navigate("map", { ...params, [MODE_PARAM]: mode });
    else setParams({ [MODE_PARAM]: mode });
  };
  return html`<div class="view-switch">
    <${Seg} label=${L.modes.label} value=${current} onChange=${choose}
      options=${[
        { value: "map", label: L.modes.map, icon: "map", title: L.modes.map_title },
        { value: "fan", label: L.modes.fan, icon: "fan", title: L.modes.fan_title },
        { value: "catalog", label: L.modes.catalog, icon: "table", title: L.modes.catalog_title },
      ]} />
  </div>`;
}
