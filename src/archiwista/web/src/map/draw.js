/**
 * Drawing an area on the map (docs/SPEC.md 6.3): a rectangle dragged with the
 * mouse or a finger, or a polygon of clicked vertices closed by a click on
 * the first one, a double click or `Enter`; `Backspace` takes the last vertex
 * back and `Esc` cancels. The shape lives in the map's `draw` source until it
 * is done; the caller turns it into an area.
 */

import { ringPolygon } from "./geo.js";

const EMPTY = { type: "FeatureCollection", features: [] };
/** Shortest side of a rectangle, px: a click is not a rectangle. */
const MIN_SIDE_PX = 8;
/** Distance from the first vertex that closes a polygon, px. */
const CLOSE_PX = 12;
/** A click this close to the last vertex adds nothing (the second click of a double click). */
const SAME_PX = 4;

/**
 * Let a person draw on the map until the shape is done or cancelled.
 *
 * @param {*} map - A MapLibre map with the `draw` source.
 * @param {"rect"|"poly"} tool
 * @param {object} handlers
 * @param {(geometry: import("../types.js").Geometry, tool: string) => void} handlers.onDone
 * @param {() => void} handlers.onCancel - `Esc`.
 * @param {(vertices: number) => void} handlers.onCount - Polygon vertices so far.
 * @returns {{stop: () => void, finish: () => void, undo: () => void}} `stop`
 *   ends drawing without a shape; `finish` and `undo` serve the buttons of the
 *   drawing hint (touch screens have no `Enter` or `Backspace`).
 */
export function startDrawing(map, tool, { onDone, onCancel, onCount }) {
  const source = map.getSource("draw");
  const container = map.getCanvasContainer();
  const points = [];
  let start = null;

  const show = (ring, closed) => {
    const features = [];
    if (ring.length >= 2) {
      const geometry =
        closed || ring.length >= 3
          ? { type: "Polygon", coordinates: [[...ring, ring[0]]] }
          : { type: "LineString", coordinates: ring };
      features.push({ type: "Feature", properties: {}, geometry });
    }
    if (tool === "poly") {
      for (const point of points) {
        features.push({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: point } });
      }
    }
    source.setData({ type: "FeatureCollection", features });
  };
  const corners = (a, b) => [
    [Math.min(a.lng, b.lng), Math.min(a.lat, b.lat)],
    [Math.max(a.lng, b.lng), Math.min(a.lat, b.lat)],
    [Math.max(a.lng, b.lng), Math.max(a.lat, b.lat)],
    [Math.min(a.lng, b.lng), Math.max(a.lat, b.lat)],
  ];
  const done = (ring) => {
    source.setData(EMPTY);
    onDone(ringPolygon(ring), tool);
  };
  const finish = () => {
    if (points.length >= 3) done([...points]);
  };
  const undo = () => {
    if (!points.length) return;
    points.pop();
    onCount(points.length);
    show(points, false);
  };

  const down = (event) => {
    if (tool !== "rect" || event.originalEvent?.touches?.length > 1) return;
    event.preventDefault();
    start = event.lngLat;
  };
  const move = (event) => {
    if (tool === "rect" && start) show(corners(start, event.lngLat), true);
    if (tool === "poly" && points.length) {
      show([...points, [event.lngLat.lng, event.lngLat.lat]], false);
    }
  };
  const up = (event) => {
    if (tool !== "rect" || !start) return;
    const from = map.project(start);
    const ring = corners(start, event.lngLat);
    start = null;
    if (Math.abs(from.x - event.point.x) < MIN_SIDE_PX || Math.abs(from.y - event.point.y) < MIN_SIDE_PX) {
      show([], false);
      return;
    }
    done(ring);
  };
  const click = (event) => {
    if (tool !== "poly") return;
    const near = (point, limit) => {
      const pixel = map.project(point);
      return Math.hypot(pixel.x - event.point.x, pixel.y - event.point.y) < limit;
    };
    if (points.length >= 3 && near(points[0], CLOSE_PX)) {
      finish();
      return;
    }
    if (points.length && near(points[points.length - 1], SAME_PX)) return;
    points.push([event.lngLat.lng, event.lngLat.lat]);
    onCount(points.length);
    show(points, false);
  };
  const doubleClick = (event) => {
    if (tool !== "poly") return;
    event.preventDefault();
    finish();
  };
  const key = (event) => {
    if (event.target instanceof HTMLElement && event.target.closest("input, select, textarea")) return;
    if (event.key === "Escape") {
      source.setData(EMPTY);
      onCancel();
    } else if (tool === "poly" && event.key === "Enter") {
      event.preventDefault();
      finish();
    } else if (tool === "poly" && event.key === "Backspace") {
      event.preventDefault();
      undo();
    }
  };

  const events = [
    ["mousedown", down],
    ["mousemove", move],
    ["mouseup", up],
    ["touchstart", down],
    ["touchmove", move],
    ["touchend", up],
    ["click", click],
    ["dblclick", doubleClick],
  ];
  for (const [name, handler] of events) map.on(name, handler);
  window.addEventListener("keydown", key);
  container.classList.add("drawing");
  map.doubleClickZoom.disable();
  if (tool === "rect") map.dragPan.disable();
  onCount(0);

  const stop = () => {
    for (const [name, handler] of events) map.off(name, handler);
    window.removeEventListener("keydown", key);
    container.classList.remove("drawing");
    map.doubleClickZoom.enable();
    map.dragPan.enable();
    source.setData(EMPTY);
  };
  return { stop, finish, undo };
}
