/**
 * Geometry of the map view in WGS84 (longitude, latitude), as the API takes
 * and returns it: bounding boxes `[min_lon, min_lat, max_lon, max_lat]`,
 * GeoJSON polygons of drawn areas and the map position kept in the address.
 */

/** Poland and Czechia: the view of an index without outlines. */
export const HOME_BOUNDS = [12.0, 48.5, 24.2, 55.0];

/** Every footprint of the index: the view that frames the data at the start. */
export const WORLD_BOUNDS = [-180, -85, 180, 85];

/** Decimal places of coordinates sent to the API (about 0.1 m). */
const DIGITS = 6;
const LAT_LIMIT = 85;
// The world at zoom 0 in MapLibre's pixels (512 px tiles).
const TILE_PX = 512;

const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
const round = (value, digits = DIGITS) => Number(value.toFixed(digits));

/**
 * A bounding box as the API's `bbox` text.
 *
 * @param {number[]} bbox - `[min_lon, min_lat, max_lon, max_lat]`.
 * @returns {string} E.g. `19.5,49.5,20.5,50.2`.
 */
export function bboxText(bbox) {
  return bbox.map((value) => round(value)).join(",");
}

/**
 * The bounding box of a GeoJSON geometry of any type.
 *
 * @param {import("../types.js").Geometry} geometry
 * @returns {number[]|null} `null` for a geometry without coordinates.
 */
export function geometryBounds(geometry) {
  const box = [Infinity, Infinity, -Infinity, -Infinity];
  const walk = (coordinates) => {
    if (typeof coordinates[0] === "number") {
      box[0] = Math.min(box[0], coordinates[0]);
      box[1] = Math.min(box[1], coordinates[1]);
      box[2] = Math.max(box[2], coordinates[0]);
      box[3] = Math.max(box[3], coordinates[1]);
      return;
    }
    for (const part of coordinates) walk(part);
  };
  walk(geometry.coordinates ?? []);
  return Number.isFinite(box[0]) ? box : null;
}

/**
 * The bounding box of several boxes.
 *
 * @param {Array<number[]|null>} boxes
 * @returns {number[]|null} `null` when there is none.
 */
export function unionBounds(boxes) {
  const found = boxes.filter(Boolean);
  if (!found.length) return null;
  return [
    Math.min(...found.map((box) => box[0])),
    Math.min(...found.map((box) => box[1])),
    Math.max(...found.map((box) => box[2])),
    Math.max(...found.map((box) => box[3])),
  ];
}

/**
 * A box at least `span` degrees wide and high around its centre, inside
 * WGS84: a single point's bounds have no area, which the API refuses as a
 * `bbox` (`400`) and which frames the map at its deepest zoom.
 *
 * @param {number[]} bbox - `[min_lon, min_lat, max_lon, max_lat]`.
 * @param {number} span - Least width and height in degrees.
 * @returns {number[]} The box itself when it is large enough.
 */
export function widenBounds(bbox, span) {
  const [west, south, east, north] = bbox;
  const grow = (low, high, limit) => {
    if (high - low >= span) return [low, high];
    const middle = (low + high) / 2;
    return [clamp(middle - span / 2, -limit, limit), clamp(middle + span / 2, -limit, limit)];
  };
  const [minLon, maxLon] = grow(west, east, 180);
  const [minLat, maxLat] = grow(south, north, LAT_LIMIT);
  return [minLon, minLat, maxLon, maxLat];
}

/**
 * The visible part of a map as a box the API accepts (inside WGS84).
 *
 * @param {*} map - A MapLibre map.
 * @returns {number[]}
 */
export function viewBounds(map) {
  const bounds = map.getBounds();
  return [
    clamp(bounds.getWest(), -180, 180),
    clamp(bounds.getSouth(), -LAT_LIMIT, LAT_LIMIT),
    clamp(bounds.getEast(), -180, 180),
    clamp(bounds.getNorth(), -LAT_LIMIT, LAT_LIMIT),
  ];
}

/**
 * A closed, counter-clockwise polygon of a box.
 *
 * @param {number[]} bbox
 * @returns {import("../types.js").Geometry}
 */
export function bboxPolygon([minLon, minLat, maxLon, maxLat]) {
  const ring = [
    [minLon, minLat],
    [maxLon, minLat],
    [maxLon, maxLat],
    [minLon, maxLat],
  ].map(([lon, lat]) => [round(lon), round(lat)]);
  return { type: "Polygon", coordinates: [[...ring, ring[0]]] };
}

/**
 * A closed polygon of drawn vertices.
 *
 * @param {Array<number[]>} points - At least three `[lon, lat]` vertices.
 * @returns {import("../types.js").Geometry}
 */
export function ringPolygon(points) {
  const ring = points.map(([lon, lat]) => [round(lon), round(lat)]);
  return { type: "Polygon", coordinates: [[...ring, ring[0]]] };
}

/**
 * The map position for the address: `center=lon,lat` and `zoom`.
 *
 * @param {*} map - A MapLibre map.
 * @returns {{center: string, zoom: string}}
 */
export function positionParams(map) {
  const { lng, lat } = map.getCenter();
  return { center: `${lng.toFixed(5)},${lat.toFixed(5)}`, zoom: map.getZoom().toFixed(2) };
}

/**
 * The map position of an address, when both parameters are valid.
 *
 * @param {Object<string, string>} params - Route parameters.
 * @returns {{center: [number, number], zoom: number}|null}
 */
export function readPosition(params) {
  const center = (params.center ?? "").split(",").map(Number);
  const zoom = Number(params.zoom);
  const valid =
    center.length === 2 &&
    center.every(Number.isFinite) &&
    Math.abs(center[0]) <= 180 &&
    Math.abs(center[1]) <= LAT_LIMIT &&
    params.zoom !== undefined &&
    Number.isFinite(zoom) &&
    zoom >= 0 &&
    zoom <= 24;
  return valid ? { center: [center[0], center[1]], zoom } : null;
}

/**
 * The box a map of `width` × `height` px shows around a position, in Web
 * Mercator with MapLibre's 512 px tiles: the view of a map that cannot be
 * drawn (no WebGL2), whose counters still count it.
 *
 * @param {[number, number]} center - `[lon, lat]`.
 * @param {number} zoom - MapLibre's zoom.
 * @param {number} width - px.
 * @param {number} height - px.
 * @returns {number[]} `[min_lon, min_lat, max_lon, max_lat]`, inside WGS84.
 */
export function centerBounds([lon, lat], zoom, width, height) {
  const size = TILE_PX * 2 ** zoom;
  const x = ((lon + 180) / 360) * size;
  const y = ((1 - Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360)) / Math.PI) / 2) * size;
  const toLon = (px) => clamp((px / size) * 360 - 180, -180, 180);
  const toLat = (py) =>
    clamp((Math.atan(Math.sinh(Math.PI * (1 - (2 * py) / size))) * 180) / Math.PI, -LAT_LIMIT, LAT_LIMIT);
  return [toLon(x - width / 2), toLat(y + height / 2), toLon(x + width / 2), toLat(y - height / 2)];
}
