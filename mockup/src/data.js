// Fixture loading and the availability model shown by every view.

import { coverage, res, day } from "./labels.js";
import { estimate, to2180, withinBox, ringArea } from "./geo.js";

export const PRODUCTS = [
  {
    id: "nmt",
    name: "NMT",
    title: "Numeryczny model terenu",
    group: "Wysokości",
    sub: "siatki 0,5–25 m, archiwa XYZ/TBD/TIN",
    color: "#15803d",
    origin: "report",
  },
  {
    id: "nmpt",
    name: "NMPT",
    title: "Numeryczny model pokrycia terenu",
    group: "Wysokości",
    sub: "siatki 0,5 m, archiwa XYZ",
    color: "#0f766e",
    origin: "report",
  },
  {
    id: "laz",
    name: "LAZ",
    title: "Chmura punktów LIDAR",
    group: "Wysokości",
    sub: "kafle LAZ, gęstość nominalna",
    color: "#7c3aed",
    origin: "report",
  },
  {
    id: "orto",
    name: "Ortofotomapa",
    title: "Ortofotomapa (arkusze wg kampanii)",
    group: "Obrazy",
    sub: "piksel 5–25 cm, RGB / CIR / B/W",
    color: "#b45309",
    origin: "index",
  },
  {
    id: "bdot10k",
    name: "BDOT10k",
    title: "Baza danych obiektów topograficznych",
    group: "Pokrycie terenu",
    sub: "pakiety powiatów, roczniki 2014–2025",
    color: "#be123c",
    origin: "packages",
  },
  {
    id: "own",
    name: "kanalizacja.gpkg",
    title: "Dane własne projektu (folder danych)",
    group: "Dane własne projektu",
    sub: "dane/ · warstwa liniowa · migawki",
    color: "#0369a1",
    origin: "own",
  },
];

/** Where the numbers come from; odd items are commands (rendered as code). */
export const ORIGINS = {
  report: ["Prawdziwy raport Kartografa: ", "kartograf elevation availability --json", " (schemat kartograf-availability/1)."],
  index: [
    "Skorowidz ortofotomapy GUGiK (WMS) zestawiony skryptem mockupu na bibliotekach Kartografa — Kartograf nie ma jeszcze raportu dostępności orto (wymaganie wobec Kartografa).",
  ],
  packages: ["Pakiety powiatów BDOT10k: powiaty obszaru z PRG, istnienie i rozmiar plików z HEAD (skrypt mockupu)."],
  own: [
    "Folder danych projektu (tylko odczyt) i migawki Archiwisty w ",
    "dane/.wersje/",
    " (A-ADR-027). Bez źródła zdalnego — bez etykiet dostępności. Sieć kanalizacyjna to dane przykładowe wygenerowane skryptem mockupu.",
  ],
};

const CHECK_PHASES = {
  report: ["Skorowidz GUGiK (WFS, roczniki)", "Maska lądu PRG", "Pomiar pokrycia na siatce 1 m"],
  index: ["Skorowidz ortofotomapy (WMS)", "Ramy arkuszy siatki", "Pomiar pokrycia"],
  packages: ["Powiaty obszaru (PRG)", "Pakiety roczników (HEAD)"],
  own: ["Folder danych projektu (odczyt)", "Migawki w .wersje/"],
};
export const phasesFor = (product) => CHECK_PHASES[PRODUCTS.find((p) => p.id === product).origin];

async function json(path) {
  const answer = await fetch(path);
  if (!answer.ok) throw new Error(`${path}: HTTP ${answer.status}`);
  return answer.json();
}

export async function loadFixtures() {
  const [area, sheets, store, nmt, nmpt, laz, orto, bdot, dNmt, dNmpt, dLaz, ortoYears, powiaty, own, nmtTiles] = await Promise.all(
    [
      "data/area.json",
      "data/derived/sheets.json",
      "data/store.json",
      "data/availability/nmt.json",
      "data/availability/nmpt.json",
      "data/availability/laz.json",
      "data/availability/orto.json",
      "data/availability/bdot10k.json",
      "data/derived/nmt.json",
      "data/derived/nmpt.json",
      "data/derived/laz.json",
      "data/derived/orto_years.json",
      "data/derived/powiaty.json",
      "data/own/kanalizacja.json",
      "data/derived/nmt_tiles.json",
    ].map(json),
  );
  area.ring2180 = area.ring4326.map(to2180);
  const reports = { nmt, nmpt, laz, orto, bdot10k: bdot };
  const raw = {
    nmt: elevationCombos("nmt", nmt, dNmt),
    nmpt: elevationCombos("nmpt", nmpt, dNmpt),
    laz: elevationCombos("laz", laz, dLaz),
    orto: ortoCombos(orto),
    bdot10k: bdotCombos(bdot),
  };
  for (const list of Object.values(raw)) for (const c of list) c.local = localState(c, store);
  const combos = Object.fromEntries(Object.entries(raw).map(([id, list]) => [id, variants(list)]));
  const powiatMap = Object.fromEntries(powiaty.powiaty.map((p) => [p.teryt, p]));
  return { area, sheets, store, reports, raw, combos, ortoYears: ortoYears.previews, tiles: { nmt: nmtTiles.tiles }, powiaty: powiatMap, own };
}

/**
 * Preview of a year layer and where it comes from (docs/PRD.md, "Widoki według
 * rodzaju danych"): orthophoto years from the GUGiK archival WMS with a time
 * dimension (also years not downloaded); elevation built from the sheets in
 * the store - a tile per downloaded sheet of that year (real files in the
 * mockup store); sheets not downloaded stay outlines.
 */
export function yearPreview(fx, product, combo) {
  if (!combo) return null;
  if (product === "orto") {
    const href = fx.ortoYears[String(combo.year)];
    return href ? { href, source: `WMS GUGiK z wymiarem czasu — stan ${combo.year}`, all: true } : null;
  }
  const byKey = fx.tiles[product]?.[`${combo.year}-${combo.resolution}-${combo.vcrs}`];
  if (!byKey || !combo.local?.members) return null;
  const tiles = [...combo.local.members].filter((code) => byKey[code]).map((code) => ({ code, ...byKey[code] }));
  if (!tiles.length) return null;
  const n = combo.sheetsFull.length + combo.sheetsPartial.length;
  return { tiles, source: `pliki arkuszy w magazynie — ${tiles.length} z ${n}` };
}

/** Lines of the own layer in state `k` and the change against state `prev` (added / removed lines). */
export function ownState(own, k, prev) {
  const live = own.features.filter((f) => f.added <= k && (f.removed === null || f.removed > k));
  const added = prev < 0 ? new Set() : new Set(live.filter((f) => f.added > prev).map((f) => f.id));
  const removed = prev < 0 ? [] : own.features.filter((f) => f.removed !== null && f.removed > prev && f.removed <= k);
  return { live, added, removed };
}

/**
 * Own data of the project folder as "years": every snapshot (oldest first)
 * and the working file ("bieżący"). `added`: snapshots made in this session.
 */
export function ownCombos(own, added = []) {
  const snaps = [...own.snapshots, ...added];
  const last = snaps[snaps.length - 1];
  const make = (s, i, current) => ({
    id: current ? "own:current" : `own:${i}`,
    product: "own",
    own: true,
    order: current ? 0 : snaps.length - i,
    year: current ? "bieżący" : day(s.date),
    yearSort: current ? 9999 : i,
    current,
    snapshot: current ? null : s,
    stateIndex: s.index,
    prevIndex: current ? last.index : i ? snaps[i - 1].index : -1,
    changedSince: current && s.sha256 !== last.sha256 ? last : null,
    lastSnapshot: current ? last : null,
    stats: { count: s.count, length: s.length_m, size: s.size_bytes, sha256: s.sha256, extent: s.extent2180 },
    horizontal: own.crs,
    source: "dane własne",
    resolution: null,
    resM: null,
    vcrs: null,
    format: "GPKG",
    color: null,
    density: null,
    dates: null,
    campaignsAll: [],
    campaignsSelected: [],
    complete: true,
    sheetsFull: [],
    sheetsPartial: [],
    uncoveredM2: 0,
    fullM2: 1,
    landM2: 1,
    sheetRecords: {},
    hints: [],
    row: own.layer,
    base: current ? "plik roboczy" : `migawka ${s.label}`,
    local: { count: 1, total: 1, members: new Set(), own: true },
  });
  return [...snaps.map((s, i) => make(s, i, false)), make(own.current, snaps.length, true)];
}

function resM(label) {
  return label ? parseFloat(label) : null;
}

function elevationCombos(product, report, derived) {
  const land = report.areas[0].land_m2;
  return report.combinations.map((c, i) => {
    const d = derived.combinations[i];
    const laz = product === "laz";
    const density = c.densities?.[0] ?? null;
    return {
      id: `${product}:${i}`,
      product,
      order: i,
      year: c.year,
      horizontal: c.horizontal,
      source: c.source,
      resolution: c.resolution,
      resM: laz ? (density ? 1 / density : null) : resM(c.resolution),
      vcrs: c.vertical_crs,
      format: c.format,
      color: null,
      density,
      dates: c.acquisition_dates,
      published: c.published,
      campaignsAll: c.campaigns,
      campaignsSelected: d.campaigns_selected,
      complete: c.complete,
      sheetsFull: c.sheets_full,
      sheetsPartial: c.sheets_partial,
      uncoveredM2: c.uncovered_m2,
      fullM2: d.full_m2,
      landM2: land,
      sheetRecords: d.sheet_records,
      hints: c.download_hint,
      row: laz ? `${density} pkt/m²` : c.resolution ? res(c.resolution) : null,
      base: laz ? `${density} pkt/m² · ${c.vertical_crs}` : [c.resolution ? res(c.resolution) : null, c.vertical_crs].filter(Boolean).join(" · "),
    };
  });
}

function ortoCombos(report) {
  const land = report.areas[0].land_m2;
  return report.combinations.map((c, i) => ({
    id: `orto:${i}`,
    product: "orto",
    order: i,
    year: c.year,
    horizontal: c.horizontal,
    source: c.source,
    resolution: c.resolution,
    resM: resM(c.resolution),
    vcrs: null,
    format: c.format,
    color: c.color,
    density: null,
    dates: c.acquisition_dates,
    published: c.published,
    campaignsAll: c.campaigns,
    campaignsSelected: c.campaigns_selected ?? c.campaigns,
    complete: c.complete,
    sheetsFull: c.sheets_full,
    sheetsPartial: c.sheets_partial,
    uncoveredM2: c.uncovered_m2,
    fullM2: c.full_m2 ?? land - c.uncovered_m2,
    landM2: land,
    sheetRecords: c.sheet_records ?? {},
    hints: c.download_hint,
    sizeMb: c.index_size_mb ?? null,
    row: res(c.resolution, { cm: true }),
    base: `${res(c.resolution, { cm: true })} · ${c.color}`,
  }));
}

function bdotCombos(report) {
  const units = report.units.map((u) => u.teryt);
  const entries = [{ ...report.current, year: null }, ...report.releases];
  return entries.map((r, i) => {
    const present = units.filter((t) => r.units[t]?.exists);
    const size = present.reduce((s, t) => s + (r.units[t].size_bytes || 0), 0);
    const current = r.year === null;
    return {
      id: `bdot10k:${i}`,
      product: "bdot10k",
      order: i,
      year: current ? "aktualne" : r.year,
      yearSort: current ? 9999 : r.year,
      horizontal: "powiaty",
      source: "pl.gugik.bdot10k",
      resolution: null,
      resM: null,
      vcrs: null,
      format: r.format,
      color: null,
      dates: null,
      campaignsAll: [],
      campaignsSelected: [],
      complete: present.length === units.length,
      sheetsFull: [],
      sheetsPartial: [],
      unitsPresent: present,
      units,
      unitInfo: r.units,
      uncoveredM2: 0,
      fullM2: present.length === units.length ? 1 : 0,
      landM2: 1,
      sheetRecords: {},
      sizeBytes: size,
      hints: [
        current
          ? report.download_hint.current
          : report.download_hint.release.replace("{year}", r.year).replace("{format}", r.format),
      ],
      row: current ? "bieżący" : "roczniki",
      base: current ? "bieżący pakiet" : "archiwum roczników",
    };
  });
}

/** Raster formats ready for a mosaic first: the default download format of a variant. */
const FORMAT_ORDER = ["ASC", "TIF", "ASCII-NMT", "XYZ", "TBD", "TIN", "TTN", "LAZ", "GPKG", "GML", "SHP"];
const formatRank = (f) => (FORMAT_ORDER.includes(f) ? FORMAT_ORDER.indexOf(f) : FORMAT_ORDER.length);

/** Store state of a variant: its format with most pieces in the store (ties: the default format). */
function bestLocal(formats) {
  return formats.reduce((best, f) => (f.local && (!best || f.local.count > best.count) ? f.local : best), null);
}

/**
 * Variants of a product (Archiwista's grouping; the Kartograf report stays
 * per format): report combinations with the same year, horizontal CRS,
 * resolution or density, vertical CRS, colour and campaigns are one data set
 * in several file formats, e.g. NMT 2019 5 m EVRF2007 as ASC and ASCII-NMT.
 * The variant carries the fields of its default format (`format`, the raster
 * ready for a mosaic); `formats` lists all of them as report combinations.
 * The format is chosen only when downloading (`inFormat`).
 */
export function variants(raw) {
  const sets = new Map();
  for (const c of raw) {
    const key = [c.year, c.horizontal, c.resolution, c.density, c.vcrs, c.color, c.campaignsAll.join("+")].join("|");
    if (!sets.has(key)) sets.set(key, []);
    sets.get(key).push(c);
  }
  return [...sets.values()]
    .map((list) => {
      const formats = [...list].sort((a, b) => formatRank(a.format) - formatRank(b.format) || a.order - b.order);
      const names = formats.map((f) => f.format).join(", ");
      const head = formats[0];
      return {
        ...head,
        order: Math.min(...formats.map((f) => f.order)),
        formats,
        row: head.row ?? names,
        variant: [head.base, names].filter(Boolean).join(" · "),
        local: bestLocal(formats) ?? head.local,
      };
    })
    .sort((a, b) => a.order - b.order);
}

/** The variant to download in one of its formats (unknown format: the default one). */
export function inFormat(v, format) {
  const f = v.formats.find((x) => x.format === format) ?? v.formats[0];
  return { ...f, id: v.id, order: v.order, formats: v.formats, row: v.row, base: v.base, variant: v.variant };
}

/** Store state of every format of a variant, including tasks of this session. */
export function withLocal(v, store, extra = []) {
  const formats = v.formats.map((f) => ({ ...f, local: localState(f, store, extra) }));
  return { ...v, formats, local: bestLocal(formats) };
}

function sameCombo(item, c) {
  if (item.product !== c.product) return false;
  if (c.product === "bdot10k") {
    return item.format === c.format && (item.current ? c.year === "aktualne" : item.year === c.year);
  }
  return (
    item.year === c.year &&
    item.horizontal === c.horizontal &&
    item.source === c.source &&
    (item.vertical_crs ?? null) === c.vcrs &&
    (item.color ?? null) === c.color &&
    (item.resolution ?? c.resolution) === c.resolution
  );
}

/** Simulated local store state of a combination (sheets or BDOT10k units). */
export function localState(c, store, extra = []) {
  if (c.product === "own") return c.local;
  const items = [...store.items, ...extra].filter((item) => sameCombo(item, c));
  const members = c.product === "bdot10k" ? c.units : [...c.sheetsFull, ...c.sheetsPartial];
  const local = new Set();
  for (const item of items) {
    const list = item.sheets === "all" || item.units === "all" ? members : item.sheets ?? item.units ?? [];
    for (const m of list) local.add(m);
  }
  const count = members.filter((m) => local.has(m)).length;
  return { count, total: members.length, members: local };
}

/** Combinations matching the variant filter of a product. */
export function matches(c, filter) {
  if (!filter) return true;
  if (filter.rows?.length && !filter.rows.includes(c.row)) return false;
  if (filter.vcrs && filter.vcrs !== "all" && c.vcrs !== filter.vcrs) return false;
  if (filter.color && filter.color !== "all" && c.color !== filter.color) return false;
  if (filter.horizontal && filter.horizontal !== "all" && c.horizontal !== filter.horizontal) return false;
  return true;
}

/**
 * Ranking inside a year (docs/SPEC.md 6.4): complete > full share > fewer
 * campaigns > finer resolution > Kartograf order.
 */
export function rank(a, b) {
  if (a.complete !== b.complete) return a.complete ? -1 : 1;
  const fa = a.fullM2 / a.landM2;
  const fb = b.fullM2 / b.landM2;
  if (Math.abs(fa - fb) > 1e-9) return fb - fa;
  const na = Math.max(1, a.campaignsSelected.length);
  const nb = Math.max(1, b.campaignsSelected.length);
  if (na !== nb) return na - nb;
  const ra = a.resM ?? Infinity;
  const rb = b.resM ?? Infinity;
  if (ra !== rb) return ra - rb;
  return a.order - b.order;
}

export function defaultFilter(product) {
  if (product === "nmt") return { rows: ["1 m"], vcrs: "all", horizontal: "all" };
  if (product === "orto") return { rows: [], color: "RGB", horizontal: "all" };
  return { rows: [], vcrs: "all", color: "all", horizontal: "all" };
}

/** Filter options present in a product's combinations. */
export function filterOptions(combos) {
  const order = (row) => combos.find((x) => x.row === row).resM ?? 1e9;
  const rows = [...new Set(combos.map((c) => c.row))].sort((a, b) => order(a) - order(b));
  const vcrs = [...new Set(combos.map((c) => c.vcrs).filter(Boolean))];
  const colors = [...new Set(combos.map((c) => c.color).filter(Boolean))];
  const horizontals = [...new Set(combos.map((c) => c.horizontal).filter((h) => h.startsWith("PL-")))].sort();
  return { rows, vcrs, colors, horizontals };
}

/**
 * Year groups of a product under a filter: newest first, every year that has
 * any combination; `best` = top-ranked matching combination (null: "brak
 * danych" in the filter), `others` = the rest of the matching ones, `hidden`
 * = combinations of the year outside the filter.
 */
export function yearGroups(combos, filter) {
  const years = [...new Set(combos.map((c) => c.year))];
  const key = (y) => (y === "aktualne" ? 9999 : typeof y === "number" ? y : combos.find((c) => c.year === y)?.yearSort ?? 0);
  years.sort((a, b) => key(b) - key(a));
  return years.map((year) => {
    const all = combos.filter((c) => c.year === year);
    const hit = all.filter((c) => matches(c, filter)).sort(rank);
    return {
      year,
      best: hit[0] ?? null,
      others: hit.slice(1),
      matching: hit,
      hidden: all.length - hit.length,
      all,
    };
  });
}

/**
 * Download hints of a combination for a user area: per-sheet commands of the
 * sheets that intersect the area, bbox commands with the area's bbox.
 */
function areaHints(hints, members, bbox) {
  const out = [];
  for (const h of hints) {
    const sheet = h.match(/--sheet (\S+)/)?.[1];
    if (sheet) {
      if (members.has(sheet)) out.push(h);
    } else out.push(h.replace(/--bbox [\d.,]+/, `--bbox ${bbox.join(",")}`));
  }
  return out;
}

/**
 * Variants for a user area inside the demo extent: the report combinations
 * re-measured (coverage estimate from the sheet frames), then grouped; the
 * demo area itself keeps the report.
 */
export function forArea(fx, product, area, ownAdded = []) {
  if (product === "own") return variants(ownCombos(fx.own, ownAdded));
  const list = fx.raw[product];
  if (!area || area.kind === "demo") return fx.combos[product];
  if (product === "bdot10k") return variants(list.map((c) => ({ ...c, hints: areaHints(c.hints, new Set(), area.bbox) })));
  const { result } = estimate(area.ring2180, list, fx.sheets);
  const out = [];
  for (const c of list) {
    const m = result.get(c.id);
    if (!m) continue;
    const next = { ...c, ...m, estimated: true, uncoveredM2: m.landM2 - m.framesM2 };
    next.hints = areaHints(c.hints, new Set([...m.sheetsFull, ...m.sheetsPartial]), area.bbox);
    next.local = localState(next, fx.store, fx.extraStore ?? []);
    out.push(next);
  }
  return variants(out);
}

export function areaInfo(ring4326, kind) {
  const ring2180 = ring4326.map(to2180);
  const xs = ring2180.map((p) => p[0]);
  const ys = ring2180.map((p) => p[1]);
  const bbox = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)].map((v) => Math.round(v));
  return {
    kind,
    ring4326,
    ring2180,
    bbox,
    areaM2: ringArea(ring2180),
    width: bbox[2] - bbox[0],
    height: bbox[3] - bbox[1],
  };
}

export const insideDemo = (fx, area) => withinBox(area.ring2180, fx.area.bbox);

export { coverage };
