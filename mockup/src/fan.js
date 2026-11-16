// "Wachlarz": the year layers of the result fanned out along an arc like a
// Dock stack in macOS. Each card is the area in EPSG:2180 drawn as SVG
// (sheets coloured by coverage; a preview only where one really exists:
// archival orthophoto WMS per year, the current relief for the newest
// elevation year; BDOT10k powiats; own data lines with the change since
// the previous snapshot).

import { useLayoutEffect, useRef, useState } from "preact/hooks";
import { html, Coverage, Local, Icon } from "./ui.js";
import { bounds } from "./geo.js";
import { coverage, localBadge, variantsMore } from "./labels.js";
import { yearPreview, ownState } from "./data.js";
import { sheetColor, FULL_COLOR, PARTIAL_COLOR, OWN_COLORS } from "./map.js";

const PLATE_W = 440;
const TITLE_TOP = 12; // .fan-title offset in styles.css
const TITLE_GAP = 14; // between the title block (it wraps on narrow stages) and the fan
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
  if (product === "own") {
    const { live, added, removed } = ownState(fx.own, combo.stateIndex, combo.prevIndex);
    const path = (x) => x.line2180.map(([px, py], i) => `${i ? "L" : "M"}${f.fx(px).toFixed(1)} ${f.fy(py).toFixed(1)}`).join(" ");
    return html`<svg viewBox=${box}>
      <rect width=${f.w} height=${f.h} fill="#f8fafc" opacity="0.35" />
      ${removed.map((x) => html`<path d=${path(x)} fill="none" stroke=${OWN_COLORS.removed} stroke-width="2.4" stroke-dasharray="5 4" />`)}
      ${live.map(
        (x) => html`<path d=${path(x)} fill="none" stroke=${added.has(x.id) ? OWN_COLORS.added : OWN_COLORS[x.kind]}
          stroke-width=${added.has(x.id) ? 3.6 : x.dia >= 1000 ? 3.2 : 1.8} stroke-linecap="round" />`,
      )}
    </svg>`;
  }
  const hatch = html`<pattern id=${`hatch-${idx}`} width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
    <rect width="7" height="7" fill="#fde68a" opacity="0.7" />
    <rect width="2.5" height="7" fill=${PARTIAL_COLOR} />
  </pattern>`;
  if (product === "bdot10k") {
    const shapes = combo.units.flatMap((t) =>
      (fx.powiaty[t]?.rings ?? []).map((r) => ({ t, pts: r.ring2180.map(f.pt).join(" "), present: combo.unitsPresent.includes(t), local: combo.local?.members?.has(t) })),
    );
    const labels = combo.units.map((t) => {
      const p = fx.powiaty[t];
      if (!p) return null;
      const [x0, y0, x1, y1] = bounds(p.rings[0].ring2180);
      const cx = Math.min(Math.max(f.fx((x0 + x1) / 2), 50), f.w - 50);
      const cy = Math.min(Math.max(f.fy((y0 + y1) / 2), 26), f.h - 10);
      return html`<text x=${cx} y=${cy} text-anchor="middle" font-size="22" font-weight="700" fill="#14532d" opacity="0.65">${t}</text>`;
    });
    return html`<svg viewBox=${box}>
      <defs>${hatch}</defs>
      ${shapes.map((s) => html`<polygon points=${s.pts} fill=${s.present ? FULL_COLOR : `url(#hatch-${idx})`} fill-opacity=${s.present ? 0.3 : 1} stroke="#ffffff" stroke-width="1.5" />`)}
      ${shapes.filter((s) => s.local).map((s) => html`<polygon points=${s.pts} fill="none" stroke="#1d4ed8" stroke-width="3" />`)}
      ${labels}
      <polygon points=${aoi} fill="none" stroke="#3730a3" stroke-width="2" />
    </svg>`;
  }
  const prev = yearPreview(fx, product, combo);
  const codes = [...combo.sheetsFull, ...combo.sheetsPartial].filter((c) => fx.sheets[c]);
  const localCodes = codes.filter((c) => combo.local?.members?.has(c));
  const ring = (c) => fx.sheets[c].ring2180.map(f.pt).join(" ");
  // elevation: a tile per downloaded sheet at its own extent; orthophoto: one image of the year clipped to the sheets
  const tiled = new Set(prev?.tiles?.map((t) => t.code) ?? []);
  const covered = (code) => (prev?.tiles ? tiled.has(code) : Boolean(prev));
  return html`<svg viewBox=${box}>
    <defs>
      ${hatch}
      ${prev?.href ? html`<clipPath id=${`clip-${idx}`}>${codes.map((c) => html`<polygon points=${ring(c)} />`)}</clipPath>` : null}
    </defs>
    ${prev?.href ? html`<g clip-path=${`url(#clip-${idx})`}>${img(prev.href)}</g>` : null}
    ${prev?.tiles?.map(({ href, bbox2180: [x0, y0, x1, y1] }) => html`<image href=${href} x=${f.fx(x0)} y=${f.fy(y1)} width=${f.fx(x1) - f.fx(x0)} height=${f.fy(y0) - f.fy(y1)} preserveAspectRatio="none" />`)}
    ${codes.map((code) => {
      const full = combo.sheetsFull.includes(code);
      const lit = covered(code);
      return html`<polygon points=${ring(code)} fill=${full ? sheetColor(combo, code) : `url(#hatch-${idx})`}
        fill-opacity=${full ? (lit ? 0.12 : 0.45) : lit ? 0.55 : 1} stroke="#ffffff" stroke-width="1" />`;
    })}
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
function Fan({ fx, area, product, groups, selectedYear, displayed, onSelectYear, result, size, top, f, texture, compact, bottom, hover, setHover }) {
  const items = groups.filter((g) => g.best).map((g) => ({ kind: "year", g, key: String(g.year) }));
  if (result?.visible && result.product === product) items.unshift({ kind: "result", key: "result" });
  const isSel = (it) => it.kind === "year" && it.g.year === selectedYear;
  const aspect = f.h / f.w;
  const H = size.h - top - bottom;
  // wide stages (ultrawide screens): larger cards and preview; labels wide enough for the whole variant
  const wideStage = size.w >= 1500;
  const LW = compact ? 150 : size.w >= 1000 ? 340 : 260;
  const R = H * 1.15; // arc radius: the middle of the fan on the left, both ends to the right
  const bulge = R - Math.sqrt(R * R - (H / 2) ** 2);
  const units = (items.length + (items.some(isSel) ? FAN_SEL - 1 : 0)) * (1 + Math.sin(FAN_ROT) / aspect);
  const hFit = (H - (items.length - 1) * FAN_GAP) / units;
  const hWide = ((size.w - 40 - bulge - 16 - LW) / FAN_SEL) * aspect;
  const h = Math.max(20, Math.min(wideStage ? 220 : 150, hFit, hWide));
  const w = h / aspect;
  const slots = items.map((it) => {
    const s = isSel(it) ? FAN_SEL : 1;
    return { it, sel: s > 1, w: w * s, h: h * s, slot: h * s + w * s * Math.sin(FAN_ROT) };
  });
  const total = slots.reduce((sum, s) => sum + s.slot, 0) + (slots.length - 1) * FAN_GAP;
  const yc = top + H / 2;
  // wide stages: the selected layer also large to the right of the labels
  const blockW = bulge + w * FAN_SEL + 16 + LW;
  const chosen = slots.find((s) => s.sel);
  const pw = chosen ? Math.min(size.w - 24 - blockW - 40 - 16, (H - 34) / aspect, wideStage ? 1100 : 620) : 0;
  const preview = pw >= 220;
  // the fan with the preview is centred: no empty strip on one side of a wide stage
  const x0 = preview ? Math.max(24, (size.w - blockW - 40 - pw) / 2) : Math.max(16, (size.w - blockW) / 2);
  let y = top + (H - total) / 2;
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
      // the selected year shows the selected set (a variant chosen in the catalog or the details panel)
      const c = s.sel && displayed ? displayed : it.g?.best;
      const hot = hover === it.key;
      const pick = () => it.kind === "year" && onSelectYear(it.g.year);
      const key = (e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault();
        pick();
      };
      const common = { onMouseEnter: () => setHover(it.key), onMouseLeave: () => setHover(null), onClick: pick };
      const lh = Math.min(s.slot, s.sel ? 132 : 64);
      return html`<div key=${it.key} class=${`fan-card ${it.kind} ${s.sel ? "sel" : ""} ${hot ? "hot" : ""}`} ...${common} aria-hidden="true"
          style=${`left:${s.cx - s.w / 2}px;top:${s.cy - s.h / 2}px;width:${s.w}px;height:${s.h}px;transform:rotate(${s.rot}rad)`}>
          <${PlateSvg} fx=${fx} f=${f} area=${area} kind="ground" />
          ${it.kind === "result"
            ? html`<${PlateSvg} fx=${fx} f=${f} area=${area} kind="result" result=${result} />`
            : html`<${PlateSvg} fx=${fx} f=${f} area=${area} combo=${c} product=${product} texture=${texture} kind="year" idx=${`f${i}`} />`}
        </div>
        <div class=${`plate-tag fan-tag ${s.sel ? "sel big" : ""} ${hot ? "hot" : ""} ${it.kind === "result" ? "result" : ""}`} ...${common}
          ...${it.kind === "year" ? { role: "button", tabindex: 0, "aria-pressed": s.sel ? "true" : "false", onKeyDown: key } : {}}
          style=${`left:${s.cx + s.w / 2 + 16}px;top:${s.cy - lh / 2}px;width:${LW}px;height:${lh}px`}
          title=${c ? `${it.g.year}: ${coverage(c).text} · ${c.variant} · ${c.horizontal} · ${localBadge(c.local).text}` : undefined}>
          ${it.kind === "result"
            ? html`<${Icon} name="file" size=${15} /><div class="tag-lines"><div style="font-weight:600;color:#1d4ed8">Wynik zadania</div>
                ${lh >= 40 ? html`<div class="sub"><span class="ell">${result.name}</span></div>` : null}</div>`
            : html`<span class="yr">${it.g.year}</span>
                <div class="tag-lines">
                  <div class="tag-top"><${Coverage} combo=${c} short=${compact || lh < 40} />${s.sel && it.g.others.length ? html`<span class="more-chip">${variantsMore(it.g.others.length)}</span>` : null}</div>
                  ${lh >= 40 && !compact ? html`<div class="sub"><${Local} local=${c.local} /><span class="ell">${c.variant} · ${c.horizontal}</span></div>` : null}
                </div>`}
        </div>`;
    })}
    ${preview ? html`<${FanPreview} fx=${fx} area=${area} product=${product} f=${f} texture=${texture} c=${displayed ?? chosen.it.g.best} year=${chosen.it.g.year}
        left=${x0 + blockW + 40} width=${pw} top=${Math.max(top, Math.min(top + H - pw * aspect - 34, chosen.cy - (pw * aspect + 34) / 2))} />` : null}
  </div>`;
}

/** Large view of the selected layer next to the fan (the same plate; its badges are on the tag, the details in the right panel). */
function FanPreview({ fx, area, product, f, texture, c, year, left, top, width }) {
  const height = width * (f.h / f.w);
  return html`<div class="fan-preview" style=${`left:${left}px;top:${top}px;width:${width}px`}>
    <div class="fan-preview-cap"><span class="yr">${year}</span><span class="ell muted">${c.variant} · ${c.horizontal}</span></div>
    <div class="fan-card sel" style=${`position:relative;width:${width}px;height:${height}px`}>
      <${PlateSvg} fx=${fx} f=${f} area=${area} kind="ground" />
      <${PlateSvg} fx=${fx} f=${f} area=${area} combo=${c} product=${product} texture=${texture} kind="year" idx="fan-preview" />
    </div>
    ${previewNote(fx, product, c)}
  </div>`;
}

export function FanView({ fx, area, product, groups, selectedYear, displayed, onSelectYear, result, visible }) {
  const stage = useRef(null);
  const title = useRef(null);
  const [size, setSize] = useState({ w: 900, h: 800 });
  const [titleH, setTitleH] = useState(58);
  const [hover, setHover] = useState(null);

  useLayoutEffect(() => {
    if (!stage.current || !title.current) return;
    const ro = new ResizeObserver(() => {
      setSize({ w: stage.current.clientWidth, h: stage.current.clientHeight });
      setTitleH(title.current.offsetHeight);
    });
    ro.observe(stage.current);
    ro.observe(title.current);
    return () => ro.disconnect();
  }, []);

  // own data: the frame is the extent of the layer (all states); BDOT10k: the whole powiats (packages cover them)
  const f = frame(product === "own" ? ownFrame(fx.own) : product === "bdot10k" ? powiatFrame(fx, groups) : area, PLATE_W);
  const layers = groups.filter((g) => g.best);
  const compact = size.w < 780;
  const bottom = size.w < 560 ? 16 : BOTTOM;
  const own = product === "own";
  const legend = own
    ? html`<span><i class="sw" style=${`background:${OWN_COLORS["ogólnospławna"]}`}></i>kolektor</span>
        <span><i class="sw" style=${`background:${OWN_COLORS.sanitarna}`}></i>sanitarna</span>
        <span><i class="sw" style=${`background:${OWN_COLORS.deszczowa}`}></i>deszczowa</span>
        <span><i class="sw" style=${`background:${OWN_COLORS.added}`}></i>dodane od poprzedniej migawki</span>
        <span><i class="sw" style=${`background:repeating-linear-gradient(90deg,${OWN_COLORS.removed} 0 4px,transparent 4px 7px)`}></i>usunięte</span>`
    : product === "bdot10k"
      ? html`<span><i class="sw" style=${`background:${FULL_COLOR}`}></i>powiat z paczką w wydaniu</span>
          <span><i class="sw hatch"></i>brak paczki</span>
          <span><i class="sw" style="outline:2px solid #1d4ed8;outline-offset:-1px"></i>w magazynie</span>
          <span class="faint">podgląd warstw — z paczki w magazynie (mockup go nie ma)</span>`
      : html`<span><i class="sw" style=${`background:${FULL_COLOR}`}></i>arkusz pełny</span>
          <span><i class="sw" style="background:linear-gradient(135deg,#0d9488 50%,#0ea5e9 50%)"></i>kampanie roku</span>
          <span><i class="sw hatch"></i>tylko rekord niepełny (NIE)</span>
          <span><i class="sw" style="outline:2px solid #1d4ed8;outline-offset:-1px"></i>w magazynie</span>
          ${product === "orto"
            ? html`<span><i class="sw" style=${`background:url(${fx.ortoYears[String(layers[0]?.year)]}) center/cover`}></i>podgląd każdego roku: archiwalny WMS GUGiK z wymiarem czasu</span>`
            : html`<span><i class="sw" style=${`background:url(${Object.values(Object.values(fx.tiles.nmt ?? {})[0] ?? {})[0]?.href ?? ""}) center/cover;outline:2px solid #1d4ed8;outline-offset:-1px`}></i>pobrany arkusz — cieniowanie z jego pliku w magazynie</span>`}`;

  return html`<div class=${`view fan-view ${visible ? "" : "hidden"} ${compact ? "compact" : ""}`}>
    <div class="fan-title" ref=${title}>
      <h3>${own ? "Wachlarz migawek" : "Wachlarz lat"} · ${layers.length} ${layers.length === 1 ? "warstwa" : layers.length < 5 ? "warstwy" : "warstw"}<span>${own ? "plik roboczy na górze, potem migawki od najnowszej" : "najnowszy rok na górze"} · każda warstwa w całości, wybrana powiększona</span></h3>
      <div class="fan-legend">
        ${legend}
      </div>
    </div>
    <div class="fan-stage" ref=${stage}>
      <${Fan} fx=${fx} area=${area} product=${product} groups=${groups} selectedYear=${selectedYear} displayed=${displayed} onSelectYear=${onSelectYear}
        result=${result} size=${size} top=${TITLE_TOP + titleH + TITLE_GAP} f=${f} compact=${compact} bottom=${bottom} hover=${hover} setHover=${setHover} />
    </div>
  </div>`;
}

/** Where the preview of the selected layer comes from (or why there is none). */
function previewNote(fx, product, c) {
  const p = yearPreview(fx, product, c);
  const note = p
    ? `podgląd: ${p.source}`
    : product === "own"
      ? "zielone — dodane od poprzedniej migawki, czerwone przerywane — usunięte"
      : ["nmt", "nmpt", "laz"].includes(product)
        ? "brak pobranych arkuszy tego roku z plikiem w magazynie mockupu — podgląd pojawi się po pobraniu; zmiany terenu pokaże też model różnic (po MVP, v1.3)"
        : null;
  return note ? html`<div class="faint fan-preview-note">${note}</div>` : null;
}

/** Frame of the own layer: extent of every line of every state, padded. */
function ownFrame(own) {
  const xs = own.features.flatMap((x) => x.line2180.map((p) => p[0]));
  const ys = own.features.flatMap((x) => x.line2180.map((p) => p[1]));
  const [x0, y0, x1, y1] = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
  const pad = Math.max(x1 - x0, y1 - y0) * 0.12;
  return { ring2180: [[x0 - pad, y1 + pad], [x1 + pad, y1 + pad], [x1 + pad, y0 - pad], [x0 - pad, y0 - pad]] };
}

/** Frame of the BDOT10k powiats of the result. */
function powiatFrame(fx, groups) {
  const units = [...new Set(groups.flatMap((g) => g.all.flatMap((c) => c.units ?? [])))];
  const pts = units.flatMap((t) => fx.powiaty[t]?.rings.flatMap((r) => r.ring2180) ?? []);
  const [x0, y0, x1, y1] = bounds(pts);
  return { ring2180: [[x0, y1], [x1, y1], [x1, y0], [x0, y0]] };
}
