// "Stos": isometric (parallel projection) stack of year layers above the area.
// Plates are CSS 3D planes with SVG content in EPSG:2180; labels sit in a 2D
// column with leader lines, positioned with the same projection.

import { useEffect, useLayoutEffect, useRef, useState } from "preact/hooks";
import { html, Coverage, Local, Icon, Seg } from "./ui.js";
import { bounds } from "./geo.js";
import { coverage, localBadge, variantsMore, span } from "./labels.js";
import { sheetColor, FULL_COLOR, PARTIAL_COLOR } from "./map.js";

const PLATE_W = 440;
const TOP = 108; // title, legend and controls
const BOTTOM = 70; // the assistant button sits in the bottom-right corner

/** Mapping of EPSG:2180 coordinates to plate pixels for the area frame. */
function frame(area, w) {
  const [x0, y0, x1, y1] = bounds(area.ring2180);
  const h = (w * (y1 - y0)) / (x1 - x0);
  const fx = (x) => ((x - x0) / (x1 - x0)) * w;
  const fy = (y) => ((y1 - y) / (y1 - y0)) * h;
  return { w, h, pt: ([x, y]) => `${fx(x).toFixed(1)},${fy(y).toFixed(1)}`, fx, fy };
}

function PlateSvg({ fx, f, area, combo, product, texture, kind, idx, result }) {
  const aoi = area.ring2180.map(f.pt).join(" ");
  const [dx0, dy0, dx1, dy1] = fx.area.bbox;
  const img = (href, opacity = 1, extra = {}) =>
    html`<image href=${href} x=${f.fx(dx0)} y=${f.fy(dy1)} width=${f.fx(dx1) - f.fx(dx0)} height=${f.fy(dy0) - f.fy(dy1)}
      preserveAspectRatio="none" opacity=${opacity} ...${extra} />`;
  const box = `0 0 ${f.w} ${f.h}`;
  if (kind === "ground") {
    // monochrome base like the map (user decision: grey basemap)
    return html`<svg viewBox=${box}>
      <defs><filter id="gray"><feColorMatrix type="saturate" values="0" /></filter></defs>
      ${img(fx.area.previews.orto, 0.9, { filter: "url(#gray)" })}
      <rect width=${f.w} height=${f.h} fill="#f8fafc" opacity="0.2" />
      <polygon points=${aoi} fill="none" stroke="#3730a3" stroke-width="2.5" />
    </svg>`;
  }
  if (kind === "result") {
    return html`<svg viewBox=${box}>
      <defs><clipPath id="clip-result"><polygon points=${aoi} /></clipPath></defs>
      <g clip-path="url(#clip-result)">${img(result?.preview ?? fx.area.previews.relief)}</g>
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

const FAN_SEL = 1.9; // enlargement of the selected layer
const FAN_GAP = 8; // px between slots
const FAN_ROT = 0.09; // rad, rotation of the outermost cards (about 5°)

/**
 * "Wachlarz": the year layers fanned out along an arc like a Dock stack in
 * macOS — every layer whole (thumbnail of the area with the year, coverage
 * and store labels), the selected one enlarged. Every card has its own
 * vertical slot sized from the stage (rotation included), so no card or
 * label covers another.
 */
function Fan({ fx, area, product, groups, selectedYear, onSelectYear, result, size, f, texture, compact, bottom, hover, setHover }) {
  const items = groups.filter((g) => g.best).map((g) => ({ kind: "year", g, key: String(g.year) }));
  if (result?.visible && result.product === product) items.unshift({ kind: "result", key: "result" });
  const isSel = (it) => it.kind === "year" && it.g.year === selectedYear;
  const aspect = f.h / f.w;
  const H = size.h - TOP - bottom;
  const LW = compact ? 150 : 260;
  const R = H * 1.15; // arc radius: the middle of the fan on the left, both ends to the right
  const bulge = R - Math.sqrt(R * R - (H / 2) ** 2);
  const units = (items.length + (items.some(isSel) ? FAN_SEL - 1 : 0)) * (1 + Math.sin(FAN_ROT) / aspect);
  const hFit = (H - (items.length - 1) * FAN_GAP) / units;
  const hWide = ((size.w - 40 - bulge - 16 - LW) / FAN_SEL) * aspect;
  const h = Math.max(20, Math.min(150, hFit, hWide));
  const w = h / aspect;
  const slots = items.map((it) => {
    const s = isSel(it) ? FAN_SEL : 1;
    return { it, sel: s > 1, w: w * s, h: h * s, slot: h * s + w * s * Math.sin(FAN_ROT) };
  });
  const total = slots.reduce((sum, s) => sum + s.slot, 0) + (slots.length - 1) * FAN_GAP;
  const yc = TOP + H / 2;
  // wide stages: the selected layer also large to the right of the labels
  const blockW = bulge + w * FAN_SEL + 16 + LW;
  const chosen = slots.find((s) => s.sel);
  const pw = chosen ? Math.min(size.w - 24 - blockW - 40 - 16, (H - 34) / aspect, 620) : 0;
  const preview = pw >= 220;
  const x0 = preview ? 24 : Math.max(16, (size.w - blockW) / 2);
  let y = TOP + (H - total) / 2;
  for (const s of slots) {
    s.cy = y + s.slot / 2;
    y += s.slot + FAN_GAP;
    const d = Math.max(-1, Math.min(1, (s.cy - yc) / (H / 2)));
    s.cx = x0 + (R - Math.sqrt(R * R - (d * H / 2) ** 2)) + (w * FAN_SEL) / 2;
    s.rot = d * FAN_ROT;
  }
  return html`<div class="fan">
    ${slots.map((s, i) => {
      const { it } = s;
      const c = it.g?.best;
      const hot = hover === it.key;
      const pick = () => it.kind === "year" && onSelectYear(it.g.year);
      const common = { onMouseEnter: () => setHover(it.key), onMouseLeave: () => setHover(null), onClick: pick };
      const lh = Math.min(s.slot, s.sel ? 132 : 64);
      return html`<div key=${it.key} class=${`fan-card ${it.kind} ${s.sel ? "sel" : ""} ${hot ? "hot" : ""}`} ...${common}
          style=${`left:${s.cx - s.w / 2}px;top:${s.cy - s.h / 2}px;width:${s.w}px;height:${s.h}px;transform:rotate(${s.rot}rad)`}>
          <${PlateSvg} fx=${fx} f=${f} area=${area} kind="ground" />
          ${it.kind === "result"
            ? html`<${PlateSvg} fx=${fx} f=${f} area=${area} kind="result" result=${result} />`
            : html`<${PlateSvg} fx=${fx} f=${f} area=${area} combo=${c} product=${product} texture=${texture} kind="year" idx=${`f${i}`} />`}
        </div>
        <div class=${`plate-tag fan-tag ${s.sel ? "sel big" : ""} ${hot ? "hot" : ""} ${it.kind === "result" ? "result" : ""}`} ...${common}
          style=${`left:${s.cx + s.w / 2 + 16}px;top:${s.cy - lh / 2}px;width:${LW}px;height:${lh}px`}
          title=${c ? `${it.g.year}: ${coverage(c).text} · ${c.variant} · ${c.horizontal} · ${localBadge(c.local).text}` : undefined}>
          ${it.kind === "result"
            ? html`<${Icon} name="file" size=${15} /><div class="tag-lines"><div style="font-weight:600;color:#1d4ed8">Wynik zadania</div>
                ${lh >= 40 ? html`<div class="sub"><span class="ell">${result.name}</span></div>` : null}</div>`
            : html`<span class="yr">${it.g.year}</span>
                <div class="tag-lines">
                  <div class="tag-top"><${Coverage} combo=${c} short=${compact || lh < 40} />${s.sel && it.g.others.length ? html`<span class="more-chip">${variantsMore(it.g.others.length)}</span>` : null}</div>
                  ${lh >= 40 && !compact ? html`<div class="sub"><${Local} local=${c.local} /><span class="ell">${c.variant} · ${c.horizontal}</span></div>` : null}
                  ${s.sel && !compact && c.dates ? html`<div class="sub"><span class="ell">nalot ${span(c.dates)}${c.campaignsSelected.length ? ` · ${c.campaignsSelected.join(", ")}` : ""}</span></div>` : null}
                </div>`}
        </div>`;
    })}
    ${preview ? html`<${FanPreview} fx=${fx} area=${area} product=${product} f=${f} texture=${texture} g=${chosen.it.g}
        left=${x0 + blockW + 40} width=${pw} top=${Math.max(TOP, Math.min(TOP + H - pw * aspect - 34, chosen.cy - (pw * aspect + 34) / 2))} />` : null}
  </div>`;
}

/** Large view of the selected layer next to the fan (the same plate, captioned). */
function FanPreview({ fx, area, product, f, texture, g, left, top, width }) {
  const c = g.best;
  const height = width * (f.h / f.w);
  return html`<div class="fan-preview" style=${`left:${left}px;top:${top}px;width:${width}px`}>
    <div class="fan-preview-cap"><span class="yr">${g.year}</span><${Coverage} combo=${c} /><${Local} local=${c.local} /><span class="ell muted">${c.variant} · ${c.horizontal}</span></div>
    <div class="fan-card sel" style=${`position:relative;width:${width}px;height:${height}px`}>
      <${PlateSvg} fx=${fx} f=${f} area=${area} kind="ground" />
      <${PlateSvg} fx=${fx} f=${f} area=${area} combo=${c} product=${product} texture=${texture} kind="year" idx="fan-preview" />
    </div>
  </div>`;
}

export function StackView({ fx, area, product, groups, selectedYear, onSelectYear, result, visible }) {
  const stage = useRef(null);
  const [size, setSize] = useState({ w: 900, h: 800 });
  // "fan": every layer whole on an arc (default); "stack": isometric stack with a slid-out year
  const [mode, setMode] = useState("fan");
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
  // label column: two lines on wide stages, one line (year + coverage) on narrow ones
  const tier = size.w < 560 ? "xs" : size.w < 780 ? "sm" : size.w < 1000 ? "md" : "lg";
  const compact = tier === "xs" || tier === "sm";
  const LW = { xs: 168, sm: 206, md: 276, lg: 312 }[tier];
  const LH = compact ? 30 : 42;
  const LGAP = { xs: 16, sm: 28, md: 40, lg: 44 }[tier];

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
  // The selected year slides out of the stack to the left (screen space) so
  // that newer layers never cover it; the layers above it turn translucent.
  const selIdx = plates.findIndex((p) => p.kind === "year" && p.g.year === selectedYear);
  const covered = selIdx > 0 && selIdx < n - 1;
  const plateW = Math.max(...corners.map((c) => proj(c[0], c[1], 0)[0])) - Math.min(...corners.map((c) => proj(c[0], c[1], 0)[0]));
  const SLIDE = 0.62 * plateW; // screen units before scaling
  const slideLocal = [-SLIDE * Math.cos(s), SLIDE * Math.sin(s)]; // plate-plane offset that projects to (-SLIDE, 0)
  const bottom = tier === "xs" ? 16 : BOTTOM;
  const spanX = maxX - minX + SLIDE; // room for the slid-out layer on the left
  const k = Math.max(0.2, Math.min(1.25, (size.w - 40 - LW - LGAP) / spanX, (size.h - TOP - bottom - 10) / (maxY - minY)));
  const ox = (size.w - (k * spanX + LGAP + LW)) / 2 - k * (minX - SLIDE);
  const oy = TOP + (size.h - TOP - bottom - k * (maxY - minY)) / 2 - k * minY;
  const sceneTransform = flat
    ? `scale(${k}) rotateX(0deg) rotateZ(0deg)`
    : `scale(${k}) rotateX(${tilt}deg) rotateZ(${spin}deg)`;
  const flatY = oy + k * ((maxY + minY) / 2);

  // label column: anchors at the right-most plate corner, pushed apart
  const labelX = ox + k * maxX + LGAP;
  const labels = plates.map((p, i) => {
    const [ax, ay] = proj(right[0], right[1], zOf(i));
    const out = covered && i === selIdx ? SLIDE : 0;
    return { key: p.key, ax: ox + k * (ax - out), ay: oy + k * ay, top: oy + k * ay - LH / 2 };
  });
  for (let i = n - 2; i >= 0; i--) labels[i].top = Math.max(labels[i].top, labels[i + 1].top + LH + 4);
  const overflow = labels[0].top + LH - (size.h - bottom + 8);
  if (overflow > 0) for (const l of labels) l.top -= overflow;
  const texture = product === "orto" ? fx.area.previews.orto : fx.area.previews.relief;

  return html`<div class=${`view stack-view ${visible ? "" : "hidden"} ${compact ? "compact" : ""}`}>
    <div class="stack-title">
      <h3>${mode === "fan" ? "Wachlarz lat" : "Stos lat"} · ${layers.length} ${layers.length === 1 ? "warstwa" : layers.length < 5 ? "warstwy" : "warstw"}<span>${mode === "fan" ? "najnowszy rok na górze · każda warstwa w całości, wybrana powiększona" : "najnowszy rok na górze · podkład = obszar"}</span></h3>
      <div class="stack-legend">
        <span><i class="sw" style=${`background:${FULL_COLOR}`}></i>arkusz pełny</span>
        <span><i class="sw" style="background:linear-gradient(135deg,#0d9488 50%,#0ea5e9 50%)"></i>kampanie roku</span>
        <span><i class="sw hatch"></i>tylko rekord niepełny (NIE)</span>
        <span><i class="sw" style=${`background:url(${texture}) center/cover;outline:2px solid #1d4ed8;outline-offset:-1px`}></i>pobrane — podgląd z magazynu</span>
      </div>
      <div class="stack-ctrl">
        <${Seg} small value=${mode} onChange=${setMode} options=${[
          { value: "fan", label: "Wachlarz", title: "Każda warstwa w całości na łuku, wybrana powiększona" },
          { value: "stack", label: "Stos", title: "Izometryczny stos warstw" },
        ]} />
        ${mode === "stack"
          ? html`<label>Odstęp<input type="range" min="16" max="90" value=${gap} onInput=${(e) => setGap(+e.target.value)} /></label>
              <label>Obrót<input type="range" min="-75" max="0" value=${spin} onInput=${(e) => setSpin(+e.target.value)} /></label>
              <label>Pochylenie<input type="range" min="30" max="72" value=${tilt} onInput=${(e) => setTilt(+e.target.value)} /></label>
              <button class="btn sm" onClick=${() => setFlat(!flat)}><${Icon} name=${flat ? "stack" : "map"} size=${14} />${flat ? "Rozłóż" : "Złóż do mapy"}</button>`
          : null}
      </div>
    </div>
    <div class="stack-stage" ref=${stage}>
      ${mode === "fan"
        ? html`<${Fan} fx=${fx} area=${area} product=${product} groups=${groups} selectedYear=${selectedYear} onSelectYear=${onSelectYear}
            result=${result} size=${size} f=${f} texture=${texture} compact=${compact} bottom=${bottom} hover=${hover} setHover=${setHover} />`
        : html`
      <div class="stack-scene" style=${`left:${ox}px;top:${flat ? flatY : oy}px;transform:${sceneTransform}`}>
        ${plates.map((p, i) => {
          const year = p.g?.year;
          const sel = year !== undefined && year === selectedYear;
          const dim = hover !== null && hover !== p.key && p.kind !== "ground";
          const above = !flat && covered && i > selIdx && hover !== p.key;
          const z = flat ? 0 : zOf(i) + (hover === p.key && p.kind !== "ground" ? 14 : 0);
          const [sx, sy] = !flat && covered && i === selIdx ? slideLocal : [0, 0];
          return html`<div key=${p.key}
            class=${`plate ${p.kind} ${sel ? "sel" : ""} ${dim ? "dim" : ""} ${above ? "above" : ""}`}
            style=${`width:${f.w}px;height:${f.h}px;transform:translate3d(${-f.w / 2 + sx}px, ${-f.h / 2 + sy}px, ${z}px)`}
            onMouseEnter=${() => setHover(p.key)} onMouseLeave=${() => setHover(null)}
            onClick=${() => year !== undefined && onSelectYear(year)}>
            <div class="plate-face">
              <${PlateSvg} fx=${fx} f=${f} area=${area} combo=${p.g?.best} product=${product} texture=${texture} kind=${p.kind} idx=${i} result=${result} />
            </div>
          </div>`;
        })}
      </div>
      <svg class=${`stack-leaders ${flat ? "" : "on"}`} width=${size.w} height=${size.h}>
        ${labels.map((l) => html`<polyline points=${`${l.ax},${l.ay} ${labelX - 14},${l.top + LH / 2} ${labelX - 2},${l.top + LH / 2}`}
          class=${hover === l.key ? "hot" : ""} />`)}
        ${labels.map((l) => html`<circle cx=${l.ax} cy=${l.ay} r="3" />`)}
      </svg>
      <div class=${`stack-labels ${flat ? "" : "on"}`}>
        ${plates.map((p, i) => {
          const l = labels[i];
          const sel = p.g && p.g.year === selectedYear;
          const style = `left:${labelX}px;top:${l.top}px;width:${LW}px;height:${LH}px`;
          const common = { onMouseEnter: () => setHover(p.key), onMouseLeave: () => setHover(null) };
          if (p.kind === "ground") {
            return html`<div class="plate-tag" style=${style} ...${common}><${Icon} name="map" size=${15} />
              <div class="tag-lines"><div style="font-weight:600">Obszar</div>${compact ? null : html`<div class="sub">ortofotomapa GUGiK (podkład)</div>`}</div></div>`;
          }
          if (p.kind === "result") {
            return html`<div class="plate-tag result" style=${style} ...${common}><${Icon} name="file" size=${15} />
              <div class="tag-lines"><div style="font-weight:600;color:#1d4ed8">Wynik zadania</div>${compact ? null : html`<div class="sub"><span class="ell">${result.name}</span></div>`}</div></div>`;
          }
          const c = p.g.best;
          return html`<div class=${`plate-tag ${sel ? "sel" : ""} ${hover === p.key ? "hot" : ""}`} style=${style} ...${common}
            title=${compact ? `${p.g.year}: ${coverage(c).text} · ${c.variant} · ${c.horizontal} · ${localBadge(c.local).text}` : undefined}
            onClick=${() => onSelectYear(p.g.year)}>
            <span class="yr">${p.g.year}</span>
            <div class="tag-lines">
              <div class="tag-top"><${Coverage} combo=${c} short=${compact} />${!compact && p.g.others.length ? html`<span class="more-chip">${variantsMore(p.g.others.length)}</span>` : null}</div>
              ${compact ? null : html`<div class="sub"><${Local} local=${c.local} /><span class="ell">${c.variant} · ${c.horizontal}</span></div>`}
            </div>
          </div>`;
        })}
      </div>`}
    </div>
  </div>`;
}
