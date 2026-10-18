/**
 * Style of the map view (docs/SPEC.md 5.4): a neutral background, at most one
 * online basemap from the settings and the packaged glyphs.
 *
 * Offline mode shows no basemap at all, so the browser asks nothing outside
 * Archiwista; online, the basemap's origin is already in the page's CSP
 * (`img-src`, `connect-src`). A basemap is a raster: `xyz` tiles, or a WMS
 * address turned into GetMap requests of 256 px Web Mercator tiles.
 */

import { GLYPHS } from "../maplibre.js";

/** Neutral background under the data (and the whole map without a basemap). */
export const BACKGROUND = "#eef0f3";
/** The layer under which a basemap goes: the first data layer. */
export const FIRST_DATA_LAYER = "cells-fill";
/** Value kept for the choice "no basemap". */
export const NO_BASEMAP = "";

const SOURCE = "basemap";
const STORAGE = "archiwista:map-basemap";
const TILE_PX = 256;
const WMS_DEFAULTS = {
  SERVICE: "WMS",
  REQUEST: "GetMap",
  VERSION: "1.1.1",
  STYLES: "",
  FORMAT: "image/png",
  TRANSPARENT: "TRUE",
};

/**
 * The style a map view starts with.
 *
 * @param {import("../types.js").BasemapSettings|null} basemap - `null`: none.
 * @returns {object} MapLibre style specification.
 */
export function mapStyle(basemap) {
  const style = {
    version: 8,
    glyphs: GLYPHS,
    sources: {},
    layers: [{ id: "background", type: "background", paint: { "background-color": BACKGROUND } }],
  };
  if (basemap) {
    style.sources[SOURCE] = basemapSource(basemap);
    style.layers.push(basemapLayer(basemap));
  }
  return style;
}

/**
 * Show another basemap (or none) without touching the data layers.
 *
 * @param {*} map - A MapLibre map with the data layers added.
 * @param {import("../types.js").BasemapSettings|null} basemap
 */
export function setBasemap(map, basemap) {
  if (map.getLayer(SOURCE)) map.removeLayer(SOURCE);
  if (map.getSource(SOURCE)) map.removeSource(SOURCE);
  if (!basemap) return;
  map.addSource(SOURCE, basemapSource(basemap));
  map.addLayer(basemapLayer(basemap), map.getLayer(FIRST_DATA_LAYER) ? FIRST_DATA_LAYER : undefined);
}

/**
 * The basemaps a person may choose: none in offline mode.
 *
 * @param {import("../types.js").Settings|undefined} settings
 * @returns {import("../types.js").BasemapSettings[]}
 */
export function availableBasemaps(settings) {
  if (!settings || settings.offline) return [];
  return settings.basemaps ?? [];
}

/**
 * The basemap shown: the one chosen in this browser, else the first one.
 *
 * @param {import("../types.js").BasemapSettings[]} basemaps
 * @param {string|null} chosen - Name kept by `keepBasemap`; `NO_BASEMAP` for none.
 * @returns {import("../types.js").BasemapSettings|null}
 */
export function pickBasemap(basemaps, chosen) {
  if (chosen === NO_BASEMAP) return null;
  return basemaps.find((basemap) => basemap.name === chosen) ?? basemaps[0] ?? null;
}

/**
 * The basemap name chosen in this browser, `NO_BASEMAP`, or `null` (none chosen).
 *
 * @returns {string|null}
 */
export function chosenBasemap() {
  try {
    return localStorage.getItem(STORAGE);
  } catch {
    return null;
  }
}

/**
 * Keep the choice of basemap in this browser.
 *
 * @param {string} name - A basemap name or `NO_BASEMAP`.
 */
export function keepBasemap(name) {
  try {
    localStorage.setItem(STORAGE, name);
  } catch {
    // Private mode: the choice lasts for this page only.
  }
}

function basemapSource(basemap) {
  return {
    type: "raster",
    tiles: [tileUrl(basemap)],
    tileSize: TILE_PX,
    maxzoom: 19,
    attribution: escapeHtml(basemap.attribution ?? ""),
  };
}

function basemapLayer(basemap) {
  return {
    id: SOURCE,
    type: "raster",
    source: SOURCE,
    paint: basemap.grayscale ? { "raster-saturation": -1 } : {},
  };
}

/**
 * The tile address of a basemap: the `xyz` template itself, or a WMS GetMap
 * template filled by MapLibre (`{bbox-epsg-3857}`); parameters already in
 * the WMS address (e.g. `LAYERS`) are kept.
 *
 * @param {import("../types.js").BasemapSettings} basemap
 * @returns {string}
 */
export function tileUrl(basemap) {
  if ((basemap.kind ?? "xyz") === "xyz") return basemap.url;
  const url = new URL(basemap.url);
  const given = new Set([...url.searchParams.keys()].map((name) => name.toUpperCase()));
  for (const [name, value] of Object.entries(WMS_DEFAULTS)) {
    if (!given.has(name)) url.searchParams.set(name, value);
  }
  for (const name of ["SRS", "CRS", "BBOX", "WIDTH", "HEIGHT"]) {
    for (const key of [...url.searchParams.keys()]) {
      if (key.toUpperCase() === name) url.searchParams.delete(key);
    }
  }
  const version = url.searchParams.get("VERSION") ?? url.searchParams.get("version") ?? "1.1.1";
  const crs = version.startsWith("1.3") ? "CRS" : "SRS";
  url.searchParams.set(crs, "EPSG:3857");
  url.searchParams.set("WIDTH", String(TILE_PX));
  url.searchParams.set("HEIGHT", String(TILE_PX));
  // MapLibre fills the box itself; its braces must stay unencoded.
  return `${url.href}&BBOX={bbox-epsg-3857}`;
}

/** Attribution is shown as HTML by MapLibre: settings text stays text. */
function escapeHtml(text) {
  return text.replace(/[&<>"']/g, (char) => `&#${char.charCodeAt(0)};`);
}
