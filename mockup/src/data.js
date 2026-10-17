// Fixture loading and the availability model shown by every view.

import { coverage, res } from "./labels.js";
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
];

/** Where the numbers come from; odd items are commands (rendered as code). */
export const ORIGINS = {
  report: ["Prawdziwy raport Kartografa: ", "kartograf elevation availability --json", " (schemat kartograf-availability/1)."],
  index: [
    "Skorowidz ortofotomapy GUGiK (WMS) zestawiony skryptem mockupu na bibliotekach Kartografa — Kartograf nie ma jeszcze raportu dostępności orto (wymaganie wobec Kartografa).",
  ],
  packages: ["Pakiety powiatów BDOT10k: powiaty obszaru z PRG, istnienie i rozmiar plików z HEAD (skrypt mockupu)."],
};

const CHECK_PHASES = {
  report: ["Skorowidz GUGiK (WFS, roczniki)", "Maska lądu PRG", "Pomiar pokrycia na siatce 1 m"],
  index: ["Skorowidz ortofotomapy (WMS)", "Ramy arkuszy siatki", "Pomiar pokrycia"],
  packages: ["Powiaty obszaru (PRG)", "Pakiety roczników (HEAD)"],
};
export const phasesFor = (product) => CHECK_PHASES[PRODUCTS.find((p) => p.id === product).origin];

async function json(path) {
  const answer = await fetch(path);
  if (!answer.ok) throw new Error(`${path}: HTTP ${answer.status}`);
  return answer.json();
}

export async function loadFixtures() {
  const [area, sheets, store, nmt, nmpt, laz, orto, bdot, dNmt, dNmpt, dLaz] = await Promise.all(
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
    ].map(json),
  );
  area.ring2180 = area.ring4326.map(to2180);
  const reports = { nmt, nmpt, laz, orto, bdot10k: bdot };
  const combos = {
    nmt: elevationCombos("nmt", nmt, dNmt),
    nmpt: elevationCombos("nmpt", nmpt, dNmpt),
    laz: elevationCombos("laz", laz, dLaz),
    orto: ortoCombos(orto),
    bdot10k: bdotCombos(bdot),
  };
  for (const list of Object.values(combos)) for (const c of list) c.local = localState(c, store);
  return { area, sheets, store, reports, combos };
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
      row: laz ? `${density} pkt/m²` : c.resolution ? res(c.resolution) : c.format === "TIN" || c.format === "TTN" ? "TIN · TTN" : c.format,
      variant: laz
        ? `${density} pkt/m² · ${c.vertical_crs}`
        : [c.resolution ? res(c.resolution) : null, c.vertical_crs, c.format].filter(Boolean).join(" · "),
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
    variant: `${res(c.resolution, { cm: true })} · ${c.color}`,
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
      row: current ? "GPKG (bieżący)" : r.format,
      variant: current ? "GPKG · bieżący pakiet" : `${r.format} · archiwum roczników`,
    };
  });
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
  const key = (y) => (y === "aktualne" ? 9999 : y);
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
 * Re-measure combinations for a user area inside the demo extent (coverage
 * estimate from the sheet frames); the demo area itself keeps the report.
 */
export function forArea(fx, product, area) {
  const list = fx.combos[product];
  if (!area || area.kind === "demo") return list;
  if (product === "bdot10k") return list.map((c) => ({ ...c, hints: areaHints(c.hints, new Set(), area.bbox) }));
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
  return out;
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
