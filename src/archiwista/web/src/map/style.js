/**
 * Style of the map view (docs/SPEC.md 5.4): a neutral background, at most one
 * online basemap from the settings and the packaged glyphs.
 *
 * Offline mode shows no basemap at all, so the browser asks nothing outside
 * Archiwista; online, the basemap's origin is already in the page's CSP
 * (`img-src`, `connect-src`). A raster basemap is `xyz` tiles, or a WMS
 * address turned into GetMap requests of 256 px Web Mercator tiles. A
 * `vector` basemap is the TileJSON of OpenMapTiles vector tiles, its tiles
 * on the same origin, drawn in Archiwista's own light grey style: land use,
 * water, boundaries, roads, and the names of places and waters — Polish
 * where the tiles have one (`name:pl`), else Latin, else local — in the
 * packaged glyphs, without the provider's sprites or fonts.
 */

import { GLYPH_FONT, GLYPHS } from "../maplibre.js";

/** Neutral background under the data (and the whole map without a basemap). */
export const BACKGROUND = "#eef0f3";
/** The layer under which a basemap goes: the first data layer. */
export const FIRST_DATA_LAYER = "cells-fill";
/** The preference's choice "no basemap" (`Preferences.basemap`). */
export const NO_BASEMAP = "";

const SOURCE = "basemap";
const TILE_PX = 256;
const WMS_DEFAULTS = {
  SERVICE: "WMS",
  REQUEST: "GetMap",
  VERSION: "1.1.1",
  STYLES: "",
  FORMAT: "image/png",
  TRANSPARENT: "TRUE",
};
// The vector style: greys a shade off the background, so the data's
// colours stay the only strong ones.
const BUILT_UP = ["residential", "suburb", "quarter", "neighbourhood", "commercial", "industrial", "retail"];
const ROADS = ["motorway", "trunk", "primary", "secondary", "tertiary", "minor"];
const LOCALITIES = ["suburb", "quarter", "neighbourhood", "hamlet", "isolated_dwelling", "locality"];
const LANDUSE = "#e4e7eb";
const WATER = "#d3d9e1";
const ROAD = "#ffffff";
const ROAD_FAR = "#d3d8df";
const CASING = "#cfd5dd";
const STATE_LINE = "#bcc3cd";
const COUNTRY_LINE = "#98a2b3";
const WATER_TEXT = "#5f6f82";
const HALO = "rgba(255, 255, 255, 0.85)";
/** Label of a place or water: Polish name, else the Latin one, else the local one. */
const NAME = ["coalesce", ["get", "name:pl"], ["get", "name:latin"], ["get", "name"]];
const POINTS = ["match", ["geometry-type"], ["Point", "MultiPoint"], true, false];
const LINES = ["match", ["geometry-type"], ["LineString", "MultiLineString"], true, false];

/**
 * Load a vector TileJSON before MapLibre can request any of its tiles.
 * The CSP permits the configured TileJSON origin only; reject the entire
 * basemap if any tile template would leave that origin.
 *
 * @param {import("../types.js").BasemapSettings|null} basemap
 * @returns {Promise<object|null>} A MapLibre source, or null for no basemap.
 */
export async function loadBasemapSource(basemap) {
  if (!basemap) return null;
  const attribution = escapeHtml(basemap.attribution ?? "");
  if (basemap.kind !== "vector") {
    return { type: "raster", tiles: [tileUrl(basemap)], tileSize: TILE_PX, maxzoom: 19, attribution };
  }
  const response = await fetch(basemap.url);
  if (!response.ok) throw new Error(`TileJSON returned ${response.status}`);
  const document = await response.json();
  if (!Array.isArray(document.tiles) || !document.tiles.length) throw new Error("TileJSON has no tiles");
  const origin = new URL(basemap.url).origin;
  const tiles = document.tiles.map((tile) => {
    if (typeof tile !== "string") throw new Error("Invalid TileJSON tile URL");
    const url = new URL(tile, basemap.url);
    if (url.origin !== origin) throw new Error("TileJSON tile origin differs from its URL");
    return url.href.replace(/%7B/gi, "{").replace(/%7D/gi, "}");
  });
  const { minzoom, maxzoom, bounds, scheme } = document;
  return { type: "vector", tiles, minzoom, maxzoom, bounds, scheme, attribution };
}

/**
 * The style a map view starts with.
 *
 * @param {import("../types.js").BasemapSettings|null} basemap - `null`: none.
 * @param {object|null} source - Validated source; null omits the basemap.
 * @returns {object} MapLibre style specification.
 */
export function mapStyle(basemap, source) {
  const style = {
    version: 8,
    glyphs: GLYPHS,
    sources: {},
    layers: [{ id: "background", type: "background", paint: { "background-color": BACKGROUND } }],
  };
  if (basemap && source) {
    style.sources[SOURCE] = source;
    style.layers.push(...basemapLayers(basemap));
  }
  return style;
}

/**
 * Show another basemap (or none) without touching the data layers.
 *
 * @param {*} map - A MapLibre map with the data layers added.
 * @param {import("../types.js").BasemapSettings|null} basemap
 * @param {object|null} source - Validated source; null removes the basemap.
 */
export function setBasemap(map, basemap, source) {
  for (const id of map.getLayersOrder()) {
    if (map.getLayer(id).source === SOURCE) map.removeLayer(id);
  }
  if (map.getSource(SOURCE)) map.removeSource(SOURCE);
  if (!basemap || !source) return;
  map.addSource(SOURCE, source);
  const before = map.getLayer(FIRST_DATA_LAYER) ? FIRST_DATA_LAYER : undefined;
  for (const layer of basemapLayers(basemap)) map.addLayer(layer, before);
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
 * The basemap shown: the one the person chose (`Preferences.basemap`), else
 * the first one.
 *
 * @param {import("../types.js").BasemapSettings[]} basemaps
 * @param {string|null} chosen - A basemap's name, `NO_BASEMAP` for none, `null`
 *   for the first.
 * @returns {import("../types.js").BasemapSettings|null}
 */
export function pickBasemap(basemaps, chosen) {
  if (chosen === NO_BASEMAP) return null;
  return basemaps.find((basemap) => basemap.name === chosen) ?? basemaps[0] ?? null;
}

function basemapLayers(basemap) {
  if (basemap.kind === "vector") return vectorLayers();
  return [
    {
      id: SOURCE,
      type: "raster",
      source: SOURCE,
      paint: basemap.grayscale ? { "raster-saturation": -1 } : {},
    },
  ];
}

/**
 * Layers of the grey style over the OpenMapTiles schema, bottom to top: the
 * labels of the highest layers win where they collide. Only places and
 * waters are named: names of parks, peaks or roads abroad would need more
 * scripts than the packaged glyphs.
 */
function vectorLayers() {
  const zoom = (...stops) => ["interpolate", ["linear"], ["zoom"], ...stops];
  const layer = (id, type, sourceLayer, filter, rest) => ({
    id: `${SOURCE}-${id}`,
    type,
    source: SOURCE,
    "source-layer": sourceLayer,
    ...(filter ? { filter } : {}),
    ...rest,
  });
  const boundary = (level, disputed) => [
    "all",
    ["==", ["get", "admin_level"], level],
    ["!=", ["get", "maritime"], 1],
    [disputed ? "==" : "!=", ["get", "disputed"], 1],
  ];
  const roads = ["all", ["match", ["get", "class"], ROADS, true, false], ["!=", ["get", "brunnel"], "tunnel"]];
  const roadWidth = (extra) => {
    const of = (motorway, primary, other) => [
      "match", ["get", "class"], ["motorway", "trunk"], motorway + extra, "primary", primary + extra, other + extra,
    ];
    return ["interpolate", ["exponential", 1.5], ["zoom"], 5, of(0.6, 0.4, 0.3), 10, of(1.6, 1.2, 0.6), 16, of(9, 7, 4)];
  };
  const label = (id, sourceLayer, filter, { size, color, minzoom = 0, maxzoom = 24, line = false, layout = {} }) =>
    layer(id, "symbol", sourceLayer, filter, {
      minzoom,
      maxzoom,
      layout: {
        "text-field": NAME,
        "text-font": [GLYPH_FONT],
        "text-size": size,
        "text-max-width": 8,
        ...(line ? { "symbol-placement": "line" } : {}),
        ...layout,
      },
      paint: { "text-color": color, "text-halo-color": HALO, "text-halo-width": 1.2 },
    });
  const place = (id, classes, options) =>
    label(id, "place", ["match", ["get", "class"], classes, true, false], {
      ...options,
      // OpenMapTiles ranks places by importance, 1 first.
      layout: { "symbol-sort-key": ["coalesce", ["get", "rank"], 99], ...options.layout },
    });
  return [
    layer("landuse", "fill", "landuse", ["match", ["get", "class"], BUILT_UP, true, false], {
      paint: { "fill-color": LANDUSE },
    }),
    layer("water", "fill", "water", null, { paint: { "fill-color": WATER } }),
    layer("waterway", "line", "waterway", ["match", ["get", "class"], ["river", "canal"], true, false], {
      paint: { "line-color": WATER, "line-width": zoom(8, 0.6, 14, 3) },
    }),
    layer("state", "line", "boundary", boundary(4, false), {
      minzoom: 5,
      paint: { "line-color": STATE_LINE, "line-width": zoom(5, 0.6, 12, 1.2), "line-dasharray": [3, 2] },
    }),
    layer("road-casing", "line", "transportation", roads, {
      minzoom: 11,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": CASING, "line-width": roadWidth(1.5) },
    }),
    layer("road", "line", "transportation", roads, {
      layout: { "line-cap": "round", "line-join": "round" },
      // Grey lines while far; white between their casings from zoom 11.
      paint: { "line-color": ["step", ["zoom"], ROAD_FAR, 11, ROAD], "line-width": roadWidth(0) },
    }),
    layer("country", "line", "boundary", boundary(2, false), {
      paint: { "line-color": COUNTRY_LINE, "line-width": zoom(3, 0.8, 10, 1.6) },
    }),
    layer("country-disputed", "line", "boundary", boundary(2, true), {
      paint: { "line-color": COUNTRY_LINE, "line-width": zoom(3, 0.8, 10, 1.6), "line-dasharray": [2, 2] },
    }),
    label("water-line-name", "water_name", LINES, { minzoom: 8, line: true, size: 11, color: WATER_TEXT }),
    label("waterway-name", "waterway", ["==", ["get", "class"], "river"], {
      minzoom: 9,
      line: true,
      size: zoom(9, 10, 14, 12),
      color: WATER_TEXT,
    }),
    label("water-name", "water_name", POINTS, { size: zoom(3, 10, 8, 13), color: WATER_TEXT }),
    place("locality", LOCALITIES, { minzoom: 12, size: zoom(12, 10, 16, 12), color: "#667085" }),
    place("village", ["village"], { minzoom: 10, size: zoom(10, 10, 15, 13), color: "#5d6878" }),
    place("town", ["town"], { minzoom: 7, size: zoom(7, 10, 13, 14), color: "#475467" }),
    place("city", ["city"], { minzoom: 4, size: zoom(4, 10.5, 8, 13, 13, 17), color: "#344054" }),
    place("country-name", ["country"], {
      maxzoom: 7,
      size: zoom(3, 10, 6, 13),
      color: "#667085",
      layout: { "text-transform": "uppercase", "text-letter-spacing": 0.08 },
    }),
  ];
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
