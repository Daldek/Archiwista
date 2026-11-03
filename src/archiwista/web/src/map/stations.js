/**
 * The stations on the map (docs/SPEC.md 6.7, 4.8.4; plan I8.1, ADR-045).
 *
 * A product whose segments belong to the producer of the station catalogs
 * (`imgw`) is drawn as its stations in place of outlines. A station is a
 * point whose shape says its type — a triangle for a water gauge, a square
 * for a climatological or synoptic station, a circle for a precipitation
 * post — and whose colour and fill say the coverage state of one variable,
 * the "Kolor punktów": green solid (continuous), orange solid (gaps), orange
 * half (partial), grey hollow (no data), grey dashed outline (unknown).
 * Never colour alone: the fill and outline tell the states apart, and the
 * legend names each (`StationSymbol` draws the same shapes as SVG). The 15
 * images `<shape>-<state>` are drawn once on a canvas and added with
 * `map.addImage`.
 *
 * The points are one GeoJSON source clustered by MapLibre; a cluster is a
 * neutral circle with its count, never a coverage colour. A click on a
 * cluster zooms to where it falls apart; one that cannot (its expansion
 * zoom is past the map's `maxZoom`, or up to `SPREAD_MAX` stations share one
 * position) spreads its stations on a circle around it with leader lines,
 * until the next click, a zoom or `Esc`. Above the limit of `GET
 * /map/stations` the answer's grid cells are drawn as the same neutral
 * circles at their centres, and a click fits the cell.
 *
 * The choices of the station view live in the address next to the filters
 * (`STATION_PARAMS`), never among them, so `GET /map/footprints` never gets
 * them: the dataset, the "Kolor punktów" variable (`color`), the station
 * types (`meteo_kind`, a comma list), the year type and whether the stations
 * on an area's boundary count (`boundary=false` leaves them out).
 */

import { count, int } from "../format.js";
import { t } from "../labels/index.js";
import { map as L } from "../labels/map.js";
import { GLYPH_FONT } from "../maplibre.js";
import { html } from "../ui.js";

/** The producer whose plugin keeps the station catalogs (IMGWTools). */
export const STATION_PRODUCER = "imgw";
/** Products that are a station kind (`kind` of `GET /map/stations`). */
export const STATION_KINDS = ["hydro", "meteo"];
/** Types of a meteo station, the type chips (`meteo_kind`). */
export const METEO_KINDS = ["synoptic", "climate", "precipitation"];
/** Address parameters of the station view; a change of product clears the first four. */
export const STATION_PARAMS = ["dataset", "color", "meteo_kind", "year_type"];
/** Address parameter that leaves out the stations on an area's boundary (`false`). */
export const BOUNDARY_PARAM = "boundary";
/** Address parameter of the station card (views/station.js): `<store>/<provider>/<code>`. */
export const STATION_PARAM = "station";
const YEAR_TYPES = ["hydrological", "calendar"];
/** The coverage states of SPEC 4.8.4, in the order of the legend. */
export const STATION_STATES = ["continuous", "gaps", "partial", "no_data", "unknown"];
/** The station shapes, in the order of the legend. */
export const STATION_SHAPES = ["triangle", "square", "circle"];
/** Most stations spread around a cluster that cannot expand. */
export const SPREAD_MAX = 8;
/** Layers a pointer can hit, the topmost first. */
export const STATION_LAYERS = ["station-spread-points", "station-points", "station-clusters", "station-cells"];

const COLORS = {
  green: "#16a34a",
  orange: "#d97706",
  grey: "#98a2b3",
  greyInk: "#667085",
  ink: "#344054",
  cluster: "#475467",
};
// Logical size of a point's image and the device pixels per unit drawn.
const ICON_PX = 18;
const ICON_RATIO = 2;
const SPREAD_RADIUS_PX = 34;
const CLUSTER_RADIUS_PX = 42;
const CLUSTER_MAX_ZOOM = 13;
const LABELS_FROM_ZOOM = 8;
const EMPTY = { type: "FeatureCollection", features: [] };

/**
 * Whether a product is drawn as stations: its segments are the station
 * producer's (`segment.producer` of `GET /products`).
 *
 * @param {import("../types.js").Product|null} product
 * @returns {boolean}
 */
export function isStationProduct(product) {
  return Boolean(product?.product) && product.segments.some((item) => item.segment.producer === STATION_PRODUCER);
}

/**
 * The station card's value of the address for a station (`STATION_PARAM`).
 *
 * @param {{store: string, provider: string, code: string}} station
 * @returns {string} `<store>/<provider>/<code>`.
 */
export function stationAddress(station) {
  return `${station.store}/${station.provider}/${station.code}`;
}

/** The view comparing stations (views/station-compare.js) and its stations' parameter. */
export const COMPARE_VIEW = "station-compare";
/** Address parameter of the stations compared: their `stationAddress`, comma-separated. */
export const COMPARE_PARAM = "stations";
/** The most stations of a comparison (SPEC 6.7, `GET /stations/compare`). */
export const MAX_COMPARED = 5;

/**
 * The address of a comparison of stations: the stations in the order of the
 * panels, the dataset and variable compared, the year type and the range.
 *
 * @param {string[]} stations - `stationAddress` of each.
 * @param {{dataset?: string|null, variable?: string|null, year_type?: string|null,
 *   from?: string|null, to?: string|null}} [choice]
 * @returns {Object<string, string|null>} Parameters of `navigate(COMPARE_VIEW, …)`.
 */
export function compareParams(stations, choice = {}) {
  return {
    [COMPARE_PARAM]: stations.slice(0, MAX_COMPARED).join(","),
    dataset: choice.dataset ?? null,
    variable: choice.variable ?? null,
    year_type: choice.year_type ?? null,
    from: choice.from ?? null,
    to: choice.to ?? null,
  };
}

/**
 * What the station view shows, from the address and `GET /stations/datasets`.
 *
 * @typedef {object} StationChoice
 * @property {import("../types.js").StationDataset[]} datasets - The product's
 *   datasets with station series, one per key (the dataset chips).
 * @property {import("../types.js").StationDataset|null} dataset - The chosen
 *   one (`dataset`), else the first; `null` without any.
 * @property {string|null} color - Key of the "Kolor punktów" variable
 *   (`color`), else the dataset's first.
 * @property {string|null} kind - The station kind of the product.
 * @property {string[]} meteoKinds - The type chips that are on; none: every type.
 * @property {"hydrological"|"calendar"|null} yearType - Of the address.
 * @property {boolean} boundary - The stations on an area's boundary count.
 */

/**
 * The choices of the station view.
 *
 * @param {Object<string, string>} params - Route parameters.
 * @param {string|null} product - The product of the filters (a family: `hydro`, `meteo`).
 * @param {import("../types.js").StationDatasets|null|undefined} answer
 * @returns {StationChoice}
 */
export function stationChoice(params, product, answer) {
  const seen = new Set();
  const datasets = (answer?.items ?? []).filter((item) => {
    if (item.kind !== product || seen.has(item.dataset)) return false;
    seen.add(item.dataset);
    return true;
  });
  const dataset = datasets.find((item) => item.dataset === params.dataset) ?? datasets[0] ?? null;
  const variables = dataset?.variables ?? [];
  const color = (variables.find((item) => item.key === params.color) ?? variables[0])?.key ?? null;
  const chosen = (params.meteo_kind ?? "").split(",");
  return {
    datasets,
    dataset,
    color,
    kind: STATION_KINDS.includes(product) ? product : null,
    meteoKinds: METEO_KINDS.filter((kind) => chosen.includes(kind)),
    yearType: YEAR_TYPES.includes(params.year_type) ? params.year_type : null,
    boundary: params[BOUNDARY_PARAM] !== "false",
  };
}

/**
 * The shape of a station: its type (SPEC 6.7; D12: a synoptic station is a
 * square like a climatological one, a meteo station of no kind too).
 *
 * @param {{kind: string|null, meteo_kind: string|null}} station
 * @returns {"triangle"|"square"|"circle"}
 */
export function stationShape(station) {
  if (station.kind === "hydro") return "triangle";
  if (station.meteo_kind === "precipitation") return "circle";
  return "square";
}

/**
 * The state of a point: its "Kolor punktów" variable's (no variable: unknown;
 * a station without the variable has no data of it).
 *
 * @param {{coverage: Object<string, {state: string}>}} station
 * @param {string|null} variable - Key of the variable, e.g. `Q`.
 * @returns {string}
 */
export function stationState(station, variable) {
  if (!variable) return "unknown";
  return station.coverage?.[variable]?.state ?? "no_data";
}

/**
 * The name of a station's type for people: "wodowskaz", "posterunek opadowy"…
 *
 * @param {{kind: string|null, meteo_kind: string|null}} station
 * @returns {string}
 */
export function stationType(station) {
  if (station.kind === "hydro") return L.stations.kind.hydro;
  return L.stations.kind[station.meteo_kind] ?? L.stations.kind.meteo;
}

/**
 * A station's shape and fill as SVG, for the legend and the lists: the
 * same drawing as the map's images. The state `shape` is the neutral fill
 * the legend draws a type with.
 *
 * @param {{shape: string, state: string, size?: number, title?: string}} props
 */
export function StationSymbol({ shape, state, size = 16, title = null }) {
  const style = fillStyle(state);
  const outline = shapePath(shape, 16);
  const half = state === "partial";
  return html`<svg class="station-symbol" width=${size} height=${size} viewBox="0 0 16 16"
    role=${title ? "img" : null} aria-label=${title} aria-hidden=${title ? null : "true"}>
    <path d=${outline} fill=${half ? "#ffffff" : style.fill} />
    ${half ? html`<path d=${halfPath(shape, 16)} fill=${style.fill} />` : null}
    <path d=${outline} fill="none" stroke=${style.stroke} stroke-width="1.6"
      stroke-dasharray=${style.dashed ? "2.4 1.8" : null} />
  </svg>`;
}

/**
 * A cluster as the map draws it, for the legend.
 *
 * @param {{label: string}} props - The count shown.
 */
export function ClusterSymbol({ label }) {
  return html`<svg class="station-symbol" width="20" height="20" viewBox="0 0 20 20" aria-hidden="true">
    <circle cx="10" cy="10" r="8.6" fill="#f2f4f7" stroke=${COLORS.cluster} stroke-width="1.4" />
    <text x="10" y="13.6" text-anchor="middle" font-size="10" fill=${COLORS.ink}>${label}</text>
  </svg>`;
}

/**
 * Add the 15 images of the points: `<shape>-<state>`, drawn once.
 *
 * @param {*} map - A MapLibre map whose style is loaded.
 */
export function addStationImages(map) {
  const side = ICON_PX * ICON_RATIO;
  const canvas = document.createElement("canvas");
  canvas.width = side;
  canvas.height = side;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  for (const shape of STATION_SHAPES) {
    for (const state of STATION_STATES) {
      context.clearRect(0, 0, side, side);
      drawSymbol(context, shape, state, side);
      map.addImage(`${shape}-${state}`, context.getImageData(0, 0, side, side), { pixelRatio: ICON_RATIO });
    }
  }
}

/**
 * Add the sources and layers of the stations, over the area, under the drawing.
 *
 * @param {*} map
 * @param {string} before - The layer they lie under.
 */
export function addStationLayers(map, before) {
  addStationImages(map);
  map.addSource("stations", {
    type: "geojson",
    data: EMPTY,
    cluster: true,
    clusterRadius: CLUSTER_RADIUS_PX,
    clusterMaxZoom: CLUSTER_MAX_ZOOM,
  });
  map.addSource("station-cells", { type: "geojson", data: EMPTY });
  map.addSource("station-spread", { type: "geojson", data: EMPTY });
  const count = {
    "text-font": [GLYPH_FONT],
    "text-size": 11.5,
    "text-allow-overlap": true,
    "text-ignore-placement": true,
  };
  const neutral = (radius) => ({
    "circle-color": "#f2f4f7",
    "circle-stroke-color": COLORS.cluster,
    "circle-stroke-width": ["case", ["boolean", ["feature-state", "hover"], false], 2.6, 1.6],
    "circle-radius": radius,
  });
  const icon = {
    "icon-image": ["get", "icon"],
    "icon-allow-overlap": true,
    "icon-ignore-placement": true,
  };
  const layers = [
    {
      id: "station-cells",
      type: "circle",
      source: "station-cells",
      paint: neutral(["interpolate", ["linear"], ["get", "share"], 0, 11, 1, 22]),
    },
    {
      id: "station-cells-count",
      type: "symbol",
      source: "station-cells",
      layout: { "text-field": ["get", "label"], ...count },
      paint: { "text-color": COLORS.ink },
    },
    {
      id: "station-clusters",
      type: "circle",
      source: "stations",
      filter: ["has", "point_count"],
      paint: neutral(["step", ["get", "point_count"], 13, 10, 16, 100, 20, 1000, 24]),
    },
    {
      id: "station-cluster-count",
      type: "symbol",
      source: "stations",
      filter: ["has", "point_count"],
      layout: { "text-field": ["get", "point_count_abbreviated"], ...count },
      paint: { "text-color": COLORS.ink },
    },
    {
      id: "station-points",
      type: "symbol",
      source: "stations",
      filter: ["!", ["has", "point_count"]],
      layout: {
        ...icon,
        "text-field": ["step", ["zoom"], "", LABELS_FROM_ZOOM, ["get", "label"]],
        "text-font": [GLYPH_FONT],
        "text-size": 11,
        "text-offset": [0, 1.1],
        "text-anchor": "top",
        "text-optional": true,
      },
      paint: { "text-color": "#1d2939", "text-halo-color": "rgba(255,255,255,0.92)", "text-halo-width": 1.3 },
    },
    {
      id: "station-spread-lines",
      type: "line",
      source: "station-spread",
      filter: ["==", ["geometry-type"], "LineString"],
      paint: { "line-color": COLORS.cluster, "line-width": 1.2 },
    },
    {
      id: "station-spread-points",
      type: "symbol",
      source: "station-spread",
      filter: ["==", ["geometry-type"], "Point"],
      layout: icon,
    },
  ];
  for (const layer of layers) map.addLayer(layer, before);
}

/**
 * The points of a map view's stations, each with its image and label.
 *
 * @param {import("../types.js").StationPoint[]} items
 * @param {string|null} variable - The "Kolor punktów" variable.
 * @returns {object} A FeatureCollection; each feature holds its index `i`.
 */
export function stationFeatures(items, variable) {
  return {
    type: "FeatureCollection",
    features: items.map((item, i) => ({
      type: "Feature",
      id: i,
      properties: { i, icon: `${stationShape(item)}-${stationState(item, variable)}`, label: pointLabel(item) },
      geometry: { type: "Point", coordinates: [item.lon, item.lat] },
    })),
  };
}

/**
 * The grid cells of an aggregated view as points at their centres.
 *
 * @param {import("../types.js").Cell[]} cells
 * @returns {object} A FeatureCollection; each feature holds its index `i`.
 */
export function cellFeatures(cells) {
  const most = cells.reduce((top, cell) => Math.max(top, cell.count), 1);
  return {
    type: "FeatureCollection",
    features: cells.map((cell, i) => ({
      type: "Feature",
      id: i,
      properties: { i, label: int(cell.count), share: Math.sqrt(cell.count / most) },
      geometry: {
        type: "Point",
        coordinates: [(cell.min_lon + cell.max_lon) / 2, (cell.min_lat + cell.max_lat) / 2],
      },
    })),
  };
}

/**
 * What a click on a cluster does: zoom to where it falls apart, or spread
 * its stations around it when it cannot.
 *
 * @param {*} map
 * @param {object} feature - The cluster's rendered feature.
 * @param {import("../types.js").StationPoint[]} items - The view's stations.
 * @param {string|null} variable - The "Kolor punktów" variable.
 * @returns {Promise<import("../types.js").StationPoint[]|null>} The stations
 *   spread, in the order of the spread points; `null` after a zoom.
 */
export async function openCluster(map, feature, items, variable) {
  const source = map.getSource("stations");
  const id = feature.properties.cluster_id;
  const center = feature.geometry.coordinates;
  const zoom = await source.getClusterExpansionZoom(id);
  const leaves =
    feature.properties.point_count <= SPREAD_MAX || zoom > map.getMaxZoom()
      ? await source.getClusterLeaves(id, SPREAD_MAX, 0)
      : [];
  if (zoom <= map.getMaxZoom() && !samePosition(leaves)) {
    map.easeTo({ center, zoom, duration: 500 });
    return null;
  }
  const stations = leaves.map((leaf) => items[leaf.properties.i]).filter(Boolean);
  spread(map, center, stations, variable);
  return stations;
}

/**
 * Spread stations on a circle around a point, with leader lines to it.
 *
 * @param {*} map
 * @param {number[]} center - `[lon, lat]` of the cluster.
 * @param {import("../types.js").StationPoint[]} stations
 * @param {string|null} variable
 */
function spread(map, center, stations, variable) {
  const middle = map.project(center);
  const features = [];
  stations.forEach((item, n) => {
    const angle = (2 * Math.PI * n) / stations.length - Math.PI / 2;
    const at = map.unproject([
      middle.x + SPREAD_RADIUS_PX * Math.cos(angle),
      middle.y + SPREAD_RADIUS_PX * Math.sin(angle),
    ]);
    const position = [at.lng, at.lat];
    features.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: [center, position] } });
    features.push({
      type: "Feature",
      id: n,
      properties: { i: n, icon: `${stationShape(item)}-${stationState(item, variable)}` },
      geometry: { type: "Point", coordinates: position },
    });
  });
  map.getSource("station-spread").setData({ type: "FeatureCollection", features });
}

/**
 * Remove the stations spread around a cluster.
 *
 * @param {*} map
 */
export function closeSpread(map) {
  map.getSource("station-spread")?.setData(EMPTY);
}

/**
 * The tooltip of a station, a cluster or a grid cell.
 *
 * @param {{tip: {kind: string, item: *}, variable: string|null}} props -
 *   `kind` is `station`, `station-cluster` or `station-cells`; `variable`
 *   the "Kolor punktów" one, marked in the labels.
 */
export function StationTip({ tip, variable }) {
  const { kind, item } = tip;
  if (kind === "station-cluster") {
    return html`<b>${t(L.stations.cluster, { count: count(item.count, L.units.stations) })}</b>
      <div class="muted">${L.stations.cluster_click}</div>`;
  }
  if (kind === "station-cells") {
    return html`<b>${t(L.stations.cell, { count: count(item.count, L.units.stations) })}</b>
      <div class="muted">${L.stations.cell_zoom}</div>`;
  }
  const entries = Object.entries(item.coverage ?? {});
  return html`<b>${item.name ?? item.code}</b>
    <div>${[stationType(item), item.river].filter(Boolean).join(" · ")}</div>
    ${item.on_boundary ? html`<div class="station-tip-boundary">${L.stations.on_boundary}</div>` : null}
    ${entries.length
      ? html`<ul class="station-tip-labels">
          ${entries.map(
            ([key, value]) => html`<li key=${key} class=${key === variable ? "chosen" : ""}>
              <${StationSymbol} shape=${stationShape(item)} state=${value.state} size=${12} />
              <span class="mono">${key}</span> <span>${value.label}</span></li>`,
          )}
        </ul>`
      : null}
    <div class="faint mono">${item.code} · ${item.provider}</div>
    <div class="muted">${L.stations.open}</div>`;
}

function pointLabel(item) {
  const name = item.name ?? item.code;
  return item.kind === "hydro" && item.river ? `${name}\n${item.river}` : name;
}

function samePosition(leaves) {
  if (leaves.length < 2) return false;
  const [lon, lat] = leaves[0].geometry.coordinates;
  return leaves.every((leaf) => leaf.geometry.coordinates[0] === lon && leaf.geometry.coordinates[1] === lat);
}

function fillStyle(state) {
  switch (state) {
    case "continuous":
      return { fill: COLORS.green, stroke: "#14532d", dashed: false };
    case "gaps":
      return { fill: COLORS.orange, stroke: "#7c2d12", dashed: false };
    case "partial":
      return { fill: COLORS.orange, stroke: "#7c2d12", dashed: false };
    case "no_data":
      return { fill: "#ffffff", stroke: COLORS.greyInk, dashed: false };
    case "shape":
      return { fill: COLORS.cluster, stroke: "#1d2939", dashed: false };
    default:
      return { fill: "#ffffff", stroke: COLORS.grey, dashed: true };
  }
}

/** The outline of a shape in a square of `side`, as an SVG path. */
function shapePath(shape, side) {
  const m = side * 0.12;
  const far = side - m;
  const mid = side / 2;
  if (shape === "triangle") return `M${mid} ${m} L${far} ${far} L${m} ${far} Z`;
  if (shape === "square") {
    const s = side * 0.18;
    return `M${s} ${s} H${side - s} V${side - s} H${s} Z`;
  }
  const r = mid - m;
  return `M${mid - r} ${mid} a${r} ${r} 0 1 0 ${2 * r} 0 a${r} ${r} 0 1 0 ${-2 * r} 0`;
}

/** The lower half of a shape (the "częściowy" fill), as an SVG path. */
function halfPath(shape, side) {
  const m = side * 0.12;
  const far = side - m;
  const mid = side / 2;
  if (shape === "triangle") {
    // Where the sides cross the middle line, from the apex down.
    const inset = ((mid - m) * (mid - m)) / (far - m);
    return `M${mid - inset} ${mid} L${mid + inset} ${mid} L${far} ${far} L${m} ${far} Z`;
  }
  if (shape === "square") {
    const s = side * 0.18;
    return `M${s} ${mid} H${side - s} V${side - s} H${s} Z`;
  }
  const r = mid - m;
  return `M${mid - r} ${mid} A${r} ${r} 0 0 0 ${mid + r} ${mid} Z`;
}

function drawSymbol(context, shape, state, side) {
  const style = fillStyle(state);
  const path = new Path2D(shapePath(shape, side));
  const half = state === "partial";
  context.save();
  context.fillStyle = half ? "#ffffff" : style.fill;
  context.fill(path);
  if (half) {
    context.fillStyle = style.fill;
    context.fill(new Path2D(halfPath(shape, side)));
  }
  context.lineWidth = 1.6 * ICON_RATIO;
  context.strokeStyle = style.stroke;
  context.setLineDash(style.dashed ? [2.4 * ICON_RATIO, 1.8 * ICON_RATIO] : []);
  context.stroke(path);
  context.restore();
}
