// "Mapa": MapLibre map with area drawing and sheet layers of the selected year.

import { useEffect, useRef, useState } from "preact/hooks";
import { html, Icon, Coverage } from "./ui.js";
import { coverage, day, plural } from "./labels.js";

const STYLE_URL = "https://tiles.openfreemap.org/styles/positron";
const FALLBACK_STYLE = {
  version: 8,
  glyphs: "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf",
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap",
    },
  },
  layers: [{ id: "osm", type: "raster", source: "osm", paint: { "raster-saturation": -0.8, "raster-opacity": 0.8 } }],
};
export const CAMPAIGN_COLORS = ["#0d9488", "#0ea5e9", "#8b5cf6", "#f43f5e"];
export const FULL_COLOR = "#16a34a";
export const PARTIAL_COLOR = "#d97706";
const EMPTY = { type: "FeatureCollection", features: [] };

const polygon = (ring, props = {}) => ({
  type: "Feature",
  properties: props,
  geometry: { type: "Polygon", coordinates: [[...ring, ring[0]]] },
});

/** Colour of a sheet: campaign colour for multi-campaign years, amber when not full. */
export function sheetColor(combo, code) {
  if (!combo.sheetsFull.includes(code)) return PARTIAL_COLOR;
  if (combo.campaignsSelected.length < 2) return FULL_COLOR;
  const campaign = combo.sheetRecords?.[code]?.campaign;
  const i = combo.campaignsSelected.indexOf(campaign);
  return CAMPAIGN_COLORS[i < 0 ? 0 : i % CAMPAIGN_COLORS.length];
}

function hatchImage() {
  const size = 10;
  const data = new Uint8Array(size * size * 4);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const on = (x + y) % size < 3;
      const k = (y * size + x) * 4;
      data.set(on ? [217, 119, 6, 210] : [253, 230, 138, 90], k);
    }
  }
  return { width: size, height: size, data };
}

export function MapView({ fx, area, drawMode, onDrawn, onCancelDraw, product, combo, yearLabel, result, visible, onSheetClick }) {
  const box = useRef(null);
  const mapRef = useRef(null);
  const [ready, setReady] = useState(false);
  const [tip, setTip] = useState(null);
  const [drawCount, setDrawCount] = useState(0);
  // handlers registered once on the map read the latest callbacks
  const cbs = useRef({});
  cbs.current = { onDrawn, onCancelDraw, onSheetClick, drawMode };

  useEffect(() => {
    let map;
    let cancelled = false;
    (async () => {
      const style = await fetch(STYLE_URL)
        .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
        .catch(() => FALLBACK_STYLE);
      if (cancelled) return;
      map = new maplibregl.Map({
        container: box.current,
        style,
        bounds: boundsOf(fx.area.ring4326),
        fitBoundsOptions: { padding: 60 },
        attributionControl: { compact: false, customAttribution: "Arkusze i podglądy: GUGiK · mockup Archiwisty" },
      });
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
      map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");
      map.on("load", () => {
        map.addImage("hatch", hatchImage(), { pixelRatio: 2 });
        map.addSource("extent", { type: "geojson", data: polygon(fx.area.ring4326) });
        map.addSource("aoi", { type: "geojson", data: EMPTY });
        map.addSource("sheets", { type: "geojson", data: EMPTY });
        map.addSource("draw", { type: "geojson", data: EMPTY });
        map.addSource("result", {
          type: "image",
          url: fx.area.previews.relief,
          coordinates: fx.area.ring4326,
        });
        map.addLayer({
          id: "result",
          type: "raster",
          source: "result",
          layout: { visibility: "none" },
          paint: { "raster-opacity": 0.92, "raster-fade-duration": 400 },
        });
        map.addLayer({
          id: "extent-line",
          type: "line",
          source: "extent",
          paint: { "line-color": "#667085", "line-width": 1.4, "line-dasharray": [3, 3] },
        });
        map.addLayer({
          id: "sheets-fill",
          type: "fill",
          source: "sheets",
          filter: ["==", ["get", "state"], "full"],
          paint: { "fill-color": ["get", "color"], "fill-opacity": ["case", ["get", "dim"], 0.04, 0.26] },
        });
        map.addLayer({
          id: "sheets-partial",
          type: "fill",
          source: "sheets",
          filter: ["==", ["get", "state"], "partial"],
          paint: { "fill-pattern": "hatch", "fill-opacity": 0.9 },
        });
        map.addLayer({
          id: "sheets-line",
          type: "line",
          source: "sheets",
          paint: { "line-color": ["get", "color"], "line-width": 1, "line-opacity": 0.85 },
        });
        map.addLayer({
          id: "sheets-local",
          type: "line",
          source: "sheets",
          filter: ["==", ["get", "local"], true],
          paint: { "line-color": "#1d4ed8", "line-width": 2.4, "line-offset": 1.2 },
        });
        map.addLayer({
          id: "sheets-hover",
          type: "line",
          source: "sheets",
          filter: ["==", ["get", "code"], ""],
          paint: { "line-color": "#111827", "line-width": 2.2 },
        });
        map.addLayer({
          id: "sheet-labels",
          type: "symbol",
          source: "sheets",
          minzoom: 13.2,
          layout: {
            "text-field": ["get", "code"],
            "text-size": 10.5,
            "text-font": ["Noto Sans Regular"],
            "text-allow-overlap": false,
          },
          paint: { "text-color": "#344054", "text-halo-color": "#fff", "text-halo-width": 1.4 },
        });
        map.addLayer({
          id: "aoi-fill",
          type: "fill",
          source: "aoi",
          paint: { "fill-color": ["coalesce", ["get", "fill"], "#4f46e5"], "fill-opacity": ["coalesce", ["get", "opacity"], 0.06] },
        });
        map.addLayer({
          id: "aoi-line",
          type: "line",
          source: "aoi",
          paint: { "line-color": "#3730a3", "line-width": 2.6 },
        });
        map.addLayer({
          id: "draw-fill",
          type: "fill",
          source: "draw",
          paint: { "fill-color": "#4f46e5", "fill-opacity": 0.12 },
        });
        map.addLayer({
          id: "draw-line",
          type: "line",
          source: "draw",
          paint: { "line-color": "#4f46e5", "line-width": 2, "line-dasharray": [2, 1.5] },
        });
        map.addLayer({
          id: "draw-pts",
          type: "circle",
          source: "draw",
          filter: ["==", ["geometry-type"], "Point"],
          paint: { "circle-radius": 4.5, "circle-color": "#fff", "circle-stroke-color": "#4f46e5", "circle-stroke-width": 2 },
        });
        const el = document.createElement("div");
        el.className = "extent-tag";
        el.innerHTML = "zasięg danych mockupu";
        el.style.cssText =
          "font:600 10.5px Inter,sans-serif;color:#475467;background:rgba(255,255,255,.9);border:1px solid #d0d5dd;border-radius:5px;padding:1px 6px;transform:translate(0,-130%)";
        new maplibregl.Marker({ element: el, anchor: "bottom-left" }).setLngLat(fx.area.ring4326[0]).addTo(map);
        const hover = (e) => {
          const f = e.features?.[0];
          if (!f) return;
          map.getCanvas().style.cursor = "pointer";
          map.setFilter("sheets-hover", ["==", ["get", "code"], f.properties.code]);
          setTip({ x: e.point.x, y: e.point.y, p: f.properties });
        };
        const leave = () => {
          map.getCanvas().style.cursor = "";
          map.setFilter("sheets-hover", ["==", ["get", "code"], ""]);
          setTip(null);
        };
        for (const id of ["sheets-fill", "sheets-partial"]) {
          map.on("mousemove", id, hover);
          map.on("mouseleave", id, leave);
          map.on("click", id, (e) => {
            if (!cbs.current.drawMode) cbs.current.onSheetClick?.(e.features?.[0]?.properties?.code);
          });
        }
        mapRef.current = map;
        setReady(true);
      });
    })();
    return () => {
      cancelled = true;
      map?.remove();
    };
  }, []);

  useEffect(() => {
    if (visible && mapRef.current) setTimeout(() => mapRef.current.resize(), 30);
  }, [visible]);

  // area outline (+ BDOT10k: coverage tint of the whole area)
  useEffect(() => {
    const map = mapRef.current;
    if (!ready) return;
    if (!area) {
      map.getSource("aoi").setData(EMPTY);
      return;
    }
    const props = {};
    if (product === "bdot10k" && combo) {
      const kind = coverage(combo).kind;
      props.fill = kind === "partial" ? PARTIAL_COLOR : FULL_COLOR;
      props.opacity = 0.18;
    }
    map.getSource("aoi").setData(polygon(area.ring4326, props));
    map.fitBounds(boundsOf(area.ring4326), { padding: { top: 70, bottom: 70, left: 60, right: 60 }, duration: 700 });
  }, [ready, area, product, combo]);

  // sheets of the displayed combination
  useEffect(() => {
    const map = mapRef.current;
    if (!ready) return;
    if (!combo || product === "bdot10k") {
      map.getSource("sheets").setData(EMPTY);
      return;
    }
    const features = [];
    for (const code of [...combo.sheetsFull, ...combo.sheetsPartial]) {
      const sheet = fx.sheets[code];
      if (!sheet) continue;
      const rec = combo.sheetRecords?.[code];
      features.push(
        polygon(sheet.ring4326, {
          code,
          state: combo.sheetsFull.includes(code) ? "full" : "partial",
          color: sheetColor(combo, code),
          campaign: rec?.campaign ?? "",
          date: rec?.date ?? "",
          records: rec?.records ?? 0,
          local: combo.local?.members?.has(code) ?? false,
          dim: Boolean(result?.visible && result.comboId === combo.id),
        }),
      );
    }
    map.getSource("sheets").setData({ type: "FeatureCollection", features });
  }, [ready, combo, product, result]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready) return;
    map.setLayoutProperty("result", "visibility", result?.visible ? "visible" : "none");
  }, [ready, result]);

  // drawing
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !drawMode) return;
    const canvas = map.getCanvas();
    canvas.style.cursor = "crosshair";
    const source = map.getSource("draw");
    let start = null;
    const pts = [];
    const show = (ring, closed) => {
      const features = [];
      if (ring.length >= 2) {
        features.push(
          closed || ring.length >= 3
            ? polygon(ring)
            : { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: ring } },
        );
      }
      for (const p of drawMode === "poly" ? pts : []) {
        features.push({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: p } });
      }
      source.setData({ type: "FeatureCollection", features });
    };
    const rect = (a, b) => [
      [Math.min(a.lng, b.lng), Math.max(a.lat, b.lat)],
      [Math.max(a.lng, b.lng), Math.max(a.lat, b.lat)],
      [Math.max(a.lng, b.lng), Math.min(a.lat, b.lat)],
      [Math.min(a.lng, b.lng), Math.min(a.lat, b.lat)],
    ];
    const finish = (ring, kind) => {
      source.setData(EMPTY);
      cbs.current.onDrawn(ring, kind);
    };
    const down = (e) => {
      if (drawMode !== "rect") return;
      e.preventDefault();
      start = e.lngLat;
    };
    const move = (e) => {
      if (drawMode === "rect" && start) show(rect(start, e.lngLat), true);
      if (drawMode === "poly" && pts.length) show([...pts, [e.lngLat.lng, e.lngLat.lat]], false);
    };
    const up = (e) => {
      if (drawMode !== "rect" || !start) return;
      const a = map.project(start);
      const b = e.point;
      const ring = rect(start, e.lngLat);
      start = null;
      if (Math.abs(a.x - b.x) < 8 || Math.abs(a.y - b.y) < 8) return show([], false);
      finish(ring, "rect");
    };
    const click = (e) => {
      if (drawMode !== "poly") return;
      const p = [e.lngLat.lng, e.lngLat.lat];
      if (pts.length >= 3) {
        const first = map.project(pts[0]);
        if (Math.hypot(first.x - e.point.x, first.y - e.point.y) < 10) return finish([...pts], "poly");
      }
      pts.push(p);
      setDrawCount(pts.length);
      show(pts, false);
    };
    const dbl = (e) => {
      if (drawMode !== "poly") return;
      e.preventDefault();
      if (pts.length >= 3) finish([...pts], "poly");
    };
    const key = (e) => {
      if (e.key === "Escape") {
        source.setData(EMPTY);
        cbs.current.onCancelDraw();
      }
      if (drawMode === "poly" && e.key === "Enter" && pts.length >= 3) finish([...pts], "poly");
      if (drawMode === "poly" && e.key === "Backspace" && pts.length) {
        pts.pop();
        setDrawCount(pts.length);
        show(pts, false);
      }
    };
    map.dragPan.disable();
    map.doubleClickZoom.disable();
    if (drawMode === "poly") map.dragPan.enable();
    map.on("mousedown", down);
    map.on("mousemove", move);
    map.on("mouseup", up);
    map.on("click", click);
    map.on("dblclick", dbl);
    window.addEventListener("keydown", key);
    setDrawCount(0);
    return () => {
      canvas.style.cursor = "";
      map.off("mousedown", down);
      map.off("mousemove", move);
      map.off("mouseup", up);
      map.off("click", click);
      map.off("dblclick", dbl);
      window.removeEventListener("keydown", key);
      map.dragPan.enable();
      map.doubleClickZoom.enable();
      source.setData(EMPTY);
    };
  }, [ready, drawMode]);

  const multi = combo && combo.campaignsSelected.length > 1;
  return html`<div class=${`view ${visible ? "" : "hidden"}`}>
    <div id="map" ref=${box}></div>
    ${drawMode
      ? html`<div class="map-hint float-card">
          <${Icon} name=${drawMode === "rect" ? "rect" : "poly"} />
          ${drawMode === "rect"
            ? html`Kliknij i przeciągnij, aby zaznaczyć prostokąt`
            : html`Klikaj wierzchołki (${drawCount}); zakończ dwuklikiem, <span class="kbd">Enter</span> albo klikiem w pierwszy punkt`}
          <span class="faint">· <span class="kbd">Esc</span> anuluje</span>
        </div>`
      : null}
    ${combo && yearLabel
      ? html`<div class="map-year-badge float-card">
          <span class="yr">${combo.year}</span>
          <div>
            <${Coverage} combo=${combo} />
            <div class="muted" style="font-size:11.5px;margin-top:3px">${combo.variant} · ${combo.horizontal}</div>
          </div>
        </div>`
      : null}
    ${combo && product !== "bdot10k"
      ? html`<div class="legend float-card">
          <div class="legend-title">Arkusze ${combo.year}</div>
          ${multi
            ? combo.campaignsSelected.map(
                (c, i) => html`<div class="legend-row">
                  <span class="sw" style=${`background:${CAMPAIGN_COLORS[i % 4]}`}></span>pełny · ${c}
                </div>`,
              )
            : html`<div class="legend-row"><span class="sw" style=${`background:${FULL_COLOR}`}></span>arkusz pełny (TAK)</div>`}
          <div class="legend-row"><span class="sw hatch"></span>tylko rekord niepełny (NIE)</div>
          <div class="legend-row"><span class="sw" style="border:2.4px solid #1d4ed8"></span>w magazynie (pobrane)</div>
          <div class="legend-row"><span class="sw" style="border:2px solid #3730a3"></span>obszar zapytania</div>
          ${result?.visible ? html`<div class="legend-row"><span class="sw" style="background:linear-gradient(135deg,#888,#eee)"></span>wynik: ${result.name}</div>` : null}
        </div>`
      : null}
    ${tip
      ? html`<div class="map-tooltip float-card" style=${`left:${tip.x}px;top:${tip.y}px`}>
          <b>${tip.p.code}</b>
          <div style="margin-top:4px">${tip.p.state === "full" ? "arkusz pełny (TAK)" : "tylko rekord niepełny (NIE)"}</div>
          <div class="muted">kampania ${tip.p.campaign || "–"} · nalot ${day(tip.p.date)}</div>
          ${tip.p.records > 1 ? html`<div class="muted">${tip.p.records} ${plural(tip.p.records, "rekord", "rekordy", "rekordów")} w arkuszu; wybrany najnowszy pełny</div>` : null}
          <div style=${`margin-top:4px;color:${tip.p.local ? "#1d4ed8" : "#98a2b3"}`}>${tip.p.local ? "w magazynie" : "niepobrany"}</div>
        </div>`
      : null}
  </div>`;
}

export function boundsOf(ring) {
  const lons = ring.map((p) => p[0]);
  const lats = ring.map((p) => p[1]);
  return [
    [Math.min(...lons), Math.min(...lats)],
    [Math.max(...lons), Math.max(...lats)],
  ];
}
