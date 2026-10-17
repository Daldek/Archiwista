// "Stos": isometric (parallel projection) stack of year layers above the area.
// Plates are CSS 3D planes with SVG content in EPSG:2180; labels sit in a 2D
// column with leader lines, positioned with the same projection.

import { useEffect, useLayoutEffect, useRef, useState } from "preact/hooks";
import { html, Coverage, Local, Icon } from "./ui.js";
import { bounds } from "./geo.js";
import { sheetColor, FULL_COLOR, PARTIAL_COLOR } from "./map.js";

const PLATE_W = 440;
const LABEL_W = 296;
const LABEL_H = 42;
const TOP = 92; // title and controls
const BOTTOM = 18;

/** Mapping of EPSG:2180 coordinates to plate pixels for the area frame. */
function frame(area, w) {
  const [x0, y0, x1, y1] = bounds(area.ring2180);
  const h = (w * (y1 - y0)) / (x1 - x0);
  const fx = (x) => ((x - x0) / (x1 - x0)) * w;
  const fy = (y) => ((y1 - y) / (y1 - y0)) * h;
  return { w, h, pt: ([x, y]) => `${fx(x).toFixed(1)},${fy(y).toFixed(1)}`, fx, fy };
}

function PlateSvg({ fx, f, area, combo, product, texture, kind, idx }) {
  const aoi = area.ring2180.map(f.pt).join(" ");
  const [dx0, dy0, dx1, dy1] = fx.area.bbox;
  const img = (href, opacity = 1) =>
    html`<image href=${href} x=${f.fx(dx0)} y=${f.fy(dy1)} width=${f.fx(dx1) - f.fx(dx0)} height=${f.fy(dy0) - f.fy(dy1)}
      preserveAspectRatio="none" opacity=${opacity} />`;
  const box = `0 0 ${f.w} ${f.h}`;
  if (kind === "ground") {
    return html`<svg viewBox=${box}>
      ${img(fx.area.previews.orto, 0.95)}
      <rect width=${f.w} height=${f.h} fill="#f8fafc" opacity="0.25" />
      <polygon points=${aoi} fill="none" stroke="#3730a3" stroke-width="2.5" />
    </svg>`;
  }
  if (kind === "result") {
    return html`<svg viewBox=${box}>
      <defs><clipPath id="clip-result"><polygon points=${aoi} /></clipPath></defs>
      <g clip-path="url(#clip-result)">${img(fx.area.previews.relief)}</g>
      <polygon points=${aoi} fill="none" stroke="#1d4ed8" stroke-width="3" />
    </svg>`;
  }
  if (product === "bdot10k") {
    const local = combo.local.count > 0;
    return html`<svg viewBox=${box}>
      <polygon points=${aoi} fill=${combo.complete ? FULL_COLOR : PARTIAL_COLOR} fill-opacity=${local ? 0.5 : 0.25}
        stroke=${local ? "#1d4ed8" : "#3730a3"} stroke-width=${local ? 4 : 2} />
      <text x=${f.w / 2} y=${f.h / 2 + 10} text-anchor="middle" font-size="30" font-weight="700" fill="#14532d" opacity="0.5">${combo.units.join(" + ")}</text>
    </svg>`;
  }
  const codes = [...combo.sheetsFull, ...combo.sheetsPartial];
  const localCodes = codes.filter((c) => combo.local?.members?.has(c));
  const ring = (c) => fx.sheets[c].ring2180.map(f.pt).join(" ");
  return html`<svg viewBox=${box}>
    <defs>
      <pattern id=${`hatch-${idx}`} width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <rect width="7" height="7" fill="#fde68a" opacity="0.7" />
        <rect width="2.5" height="7" fill=${PARTIAL_COLOR} />
      </pattern>
      ${localCodes.length ? html`<clipPath id=${`clip-${idx}`}>${localCodes.map((c) => html`<polygon points=${ring(c)} />`)}</clipPath>` : null}
    </defs>
    ${codes.map((code) => {
      if (!fx.sheets[code]) return null;
      const full = combo.sheetsFull.includes(code);
      return html`<polygon points=${ring(code)} fill=${full ? sheetColor(combo, code) : `url(#hatch-${idx})`}
        fill-opacity=${full ? 0.45 : 1} stroke="#ffffff" stroke-width="1" />`;
    })}
    ${localCodes.length ? html`<g clip-path=${`url(#clip-${idx})`}>${img(texture)}</g>` : null}
    ${localCodes.map((c) => html`<polygon points=${ring(c)} fill="none" stroke="#1d4ed8" stroke-width="2.5" />`)}
    <polygon points=${aoi} fill="none" stroke="#3730a3" stroke-width="2" />
  </svg>`;
}

export function StackView({ fx, area, product, groups, selectedYear, onSelectYear, result, visible }) {
  const stage = useRef(null);
  const [size, setSize] = useState({ w: 900, h: 800 });
  const [gap, setGap] = useState(48);
  const [spin, setSpin] = useState(-38);
  const [tilt, setTilt] = useState(58);
  const [flat, setFlat] = useState(true);
  const [hover, setHover] = useState(null);

  useLayoutEffect(() => {
    if (!stage.current) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(stage.current);
    return () => ro.disconnect();
  }, []);

  // entering the view: unfold the layers from the flat map
  useEffect(() => {
    if (!visible) {
      setFlat(true);
      return;
    }
    const t = setTimeout(() => setFlat(false), 80);
    return () => clearTimeout(t);
  }, [visible, product]);

  const f = frame(area, PLATE_W);
  const layers = groups.filter((g) => g.best).slice().reverse(); // oldest at the bottom
  const plates = [{ kind: "ground", key: "ground" }, ...layers.map((g) => ({ kind: "year", g, key: String(g.year) }))];
  if (result?.visible && result.product === product) plates.push({ kind: "result", key: "result" });
  const n = plates.length;

  // parallel projection of the final (unfolded) state
  const t = (tilt * Math.PI) / 180;
  const s = (spin * Math.PI) / 180;
  const zOf = (i) => (i === 0 ? 0 : gap * (i + 0.7));
  const proj = (x, y, z) => [x * Math.cos(s) - y * Math.sin(s), (x * Math.sin(s) + y * Math.cos(s)) * Math.cos(t) - z * Math.sin(t)];
  const corners = [
    [-f.w / 2, -f.h / 2],
    [f.w / 2, -f.h / 2],
    [f.w / 2, f.h / 2],
    [-f.w / 2, f.h / 2],
  ];
  const right = corners.reduce((best, c) => (proj(c[0], c[1], 0)[0] > proj(best[0], best[1], 0)[0] ? c : best));
  const pts = corners.flatMap(([x, y]) => [proj(x, y, 0), proj(x, y, zOf(n - 1))]);
  const minX = Math.min(...pts.map((p) => p[0]));
  const maxX = Math.max(...pts.map((p) => p[0]));
  const minY = Math.min(...pts.map((p) => p[1]));
  const maxY = Math.max(...pts.map((p) => p[1]));
  const k = Math.max(0.3, Math.min(1.25, (size.w - 48 - LABEL_W - 40) / (maxX - minX), (size.h - TOP - BOTTOM - 10) / (maxY - minY)));
  const ox = (size.w - (k * (maxX - minX) + 40 + LABEL_W)) / 2 - k * minX;
  const oy = TOP + (size.h - TOP - BOTTOM - k * (maxY - minY)) / 2 - k * minY;
  const sceneTransform = flat
    ? `scale(${k}) rotateX(0deg) rotateZ(0deg)`
    : `scale(${k}) rotateX(${tilt}deg) rotateZ(${spin}deg)`;
  const flatY = oy + k * ((maxY + minY) / 2);

  // label column: anchors at the right-most plate corner, pushed apart
  const labelX = ox + k * maxX + 40;
  const labels = plates.map((p, i) => {
    const [ax, ay] = proj(right[0], right[1], zOf(i));
    return { key: p.key, ax: ox + k * ax, ay: oy + k * ay, top: oy + k * ay - LABEL_H / 2 };
  });
  for (let i = n - 2; i >= 0; i--) labels[i].top = Math.max(labels[i].top, labels[i + 1].top + LABEL_H + 4);
  const overflow = labels[0].top + LABEL_H - (size.h - 8);
  if (overflow > 0) for (const l of labels) l.top -= overflow;
  const texture = product === "orto" ? fx.area.previews.orto : fx.area.previews.relief;

  return html`<div class=${`view stack-view ${visible ? "" : "hidden"}`}>
    <div class="stack-title">
      <h3>Stos lat · ${layers.length} ${layers.length === 1 ? "warstwa" : layers.length < 5 ? "warstwy" : "warstw"}</h3>
      <p>Najnowszy rok na górze, podkład = obszar. Tekstura na arkuszach = podgląd z magazynu (pobrane).</p>
      <div class="stack-ctrl">
        <label>Odstęp<input type="range" min="16" max="90" value=${gap} onInput=${(e) => setGap(+e.target.value)} /></label>
        <label>Obrót<input type="range" min="-75" max="0" value=${spin} onInput=${(e) => setSpin(+e.target.value)} /></label>
        <label>Pochylenie<input type="range" min="30" max="72" value=${tilt} onInput=${(e) => setTilt(+e.target.value)} /></label>
        <button class="btn sm" onClick=${() => setFlat(!flat)}><${Icon} name=${flat ? "stack" : "map"} size=${14} />${flat ? "Rozłóż" : "Złóż do mapy"}</button>
      </div>
    </div>
    <div class="stack-stage" ref=${stage}>
      <div class="stack-scene" style=${`left:${ox}px;top:${flat ? flatY : oy}px;transform:${sceneTransform}`}>
        ${plates.map((p, i) => {
          const year = p.g?.year;
          const sel = year !== undefined && year === selectedYear;
          const dim = hover !== null && hover !== p.key && p.kind !== "ground";
          const z = flat ? 0 : zOf(i) + (hover === p.key && p.kind !== "ground" ? 14 : 0);
          return html`<div key=${p.key}
            class=${`plate ${p.kind} ${sel ? "sel" : ""} ${dim ? "dim" : ""}`}
            style=${`width:${f.w}px;height:${f.h}px;transform:translate3d(${-f.w / 2}px, ${-f.h / 2}px, ${z}px)`}
            onMouseEnter=${() => setHover(p.key)} onMouseLeave=${() => setHover(null)}
            onClick=${() => year !== undefined && onSelectYear(year)}>
            <div class="plate-face">
              <${PlateSvg} fx=${fx} f=${f} area=${area} combo=${p.g?.best} product=${product} texture=${texture} kind=${p.kind} idx=${i} />
            </div>
          </div>`;
        })}
      </div>
      <svg class=${`stack-leaders ${flat ? "" : "on"}`} width=${size.w} height=${size.h}>
        ${labels.map((l) => html`<polyline points=${`${l.ax},${l.ay} ${labelX - 16},${l.top + LABEL_H / 2} ${labelX - 2},${l.top + LABEL_H / 2}`}
          class=${hover === l.key ? "hot" : ""} />`)}
        ${labels.map((l) => html`<circle cx=${l.ax} cy=${l.ay} r="3" />`)}
      </svg>
      <div class=${`stack-labels ${flat ? "" : "on"}`}>
        ${plates.map((p, i) => {
          const l = labels[i];
          const sel = p.g && p.g.year === selectedYear;
          const style = `left:${labelX}px;top:${l.top}px;width:${LABEL_W}px`;
          const common = { onMouseEnter: () => setHover(p.key), onMouseLeave: () => setHover(null) };
          if (p.kind === "ground") {
            return html`<div class="plate-tag" style=${style} ...${common}><${Icon} name="map" size=${15} />
              <div><div style="font-weight:600">Obszar</div><div class="sub">ortofotomapa GUGiK (podkład)</div></div></div>`;
          }
          if (p.kind === "result") {
            return html`<div class="plate-tag result" style=${style} ...${common}><${Icon} name="file" size=${15} />
              <div><div style="font-weight:600;color:#1d4ed8">Wynik zadania</div><div class="sub">${result.name}</div></div></div>`;
          }
          const c = p.g.best;
          return html`<div class=${`plate-tag ${sel ? "sel" : ""} ${hover === p.key ? "hot" : ""}`} style=${style} ...${common}
            onClick=${() => onSelectYear(p.g.year)}>
            <span class="yr">${p.g.year}</span>
            <div style="display:grid;gap:2px;min-width:0">
              <div style="display:flex;gap:4px;align-items:center"><${Coverage} combo=${c} /></div>
              <div class="sub"><${Local} local=${c.local} /> ${c.variant} · ${c.horizontal}${p.g.others.length ? ` · +${p.g.others.length}` : ""}</div>
            </div>
          </div>`;
        })}
      </div>
    </div>
    <div class="stack-legend float-card">
      <div class="legend-row"><span class="sw" style=${`background:${FULL_COLOR}`}></span>arkusz pełny
        <span class="sw" style="background:linear-gradient(135deg,#0d9488 50%,#0ea5e9 50%);margin-left:8px"></span>kampanie roku</div>
      <div class="legend-row"><span class="sw hatch"></span>tylko rekord niepełny (NIE)</div>
      <div class="legend-row"><span class="sw" style=${`background:url(${texture}) center/cover;border:2px solid #1d4ed8`}></span>pobrane — podgląd z magazynu</div>
      <div class="faint" style="font-size:11px">Lata bez danych w filtrze nie mają warstwy (są w Zestawieniu).</div>
    </div>
  </div>`;
}
