// Coverage vocabulary (agreed with docs/SPEC.md 6.4) and Polish formatting.

const NUM = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const INT = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 0 });
const ONE = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 1, minimumFractionDigits: 1 });
const STAMP = new Intl.DateTimeFormat("pl-PL", {
  timeZone: "Europe/Warsaw",
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

/** Polish plural form: plural(2, "kampania", "kampanie", "kampanii"). */
export function plural(n, one, few, many) {
  const tens = n % 100;
  const units = n % 10;
  if (n === 1) return one;
  if (units >= 2 && units <= 4 && !(tens >= 12 && tens <= 14)) return few;
  return many;
}

export const km2 = (m2) => `${NUM.format(m2 / 1e6)} km²`;
export const km2short = (m2) => `${ONE.format(m2 / 1e6)} km²`;
export const int = (n) => INT.format(n);
export const stamp = (iso) => STAMP.format(new Date(iso)).replace(",", "");
export const mb = (bytes) => (bytes >= 1e9 ? `${ONE.format(bytes / 1e9)} GB` : `${INT.format(bytes / 1e6)} MB`);

/** "2024-06-21" -> "21.06.2024". */
export function day(iso) {
  if (!iso) return "–";
  const [y, m, d] = iso.split("-");
  return `${d}.${m}.${y}`;
}

/** Flight date span: "28.04.2025" or "21.06–30.07.2024". */
export function span(pair) {
  if (!pair || !pair[0]) return "–";
  const [a, b] = pair;
  if (a === b) return day(a);
  const [ya, ma, da] = a.split("-");
  const [yb] = b.split("-");
  return ya === yb ? `${da}.${ma}–${day(b)}` : `${day(a)}–${day(b)}`;
}

/** "0.5m" -> "0,5 m", "0.05m" -> "5 cm" (imagery), null -> "". */
export function res(label, { cm = false } = {}) {
  if (!label) return "";
  const value = parseFloat(label);
  if (cm && value < 1) return `${INT.format(Math.round(value * 100))} cm`;
  return `${String(value).replace(".", ",")} m`;
}

/**
 * Coverage label of a combination (docs/SPEC.md 6.4):
 * - "pełne": complete, one campaign covers the land with full sheets;
 * - "pełne · N kampanie": complete only with full sheets of N campaigns
 *   (campaigns of the records selected for download);
 * - "częściowe · X%": not complete; X = land inside frames of full sheets
 *   (lower bound, proposed Kartograf field full_m2), floor so that an
 *   incomplete combination never reads 100%; "N ark. niepełnych" when some
 *   sheets have only records declared not full.
 */
export function coverage(c) {
  if (!c) return { kind: "none", text: "brak danych" };
  if (c.complete) {
    const n = c.campaignsSelected.length;
    if (n > 1) return { kind: "multi", text: `pełne · ${n} ${plural(n, "kampania", "kampanie", "kampanii")}`, campaigns: n };
    return { kind: "full", text: "pełne", campaigns: 1 };
  }
  const share = c.landM2 > 0 ? c.fullM2 / c.landM2 : 0;
  const pct = Math.floor(share * 100);
  let text = `częściowe · ${share > 0 && pct === 0 ? "<1" : pct}%`;
  const partial = c.sheetsPartial.length;
  if (partial) text += ` · ${partial} ark. ${plural(partial, "niepełny", "niepełne", "niepełnych")}`;
  return { kind: "partial", text, pct: share * 100 };
}

/** Local store badge (docs/SPEC.md 6.4): "pobrane" / "pobrane 5/12" / "niepobrane". */
export function localBadge(local) {
  if (!local || local.count === 0) return { kind: "no", text: "niepobrane" };
  if (local.count >= local.total) return { kind: "done", text: "pobrane" };
  return { kind: "some", text: `pobrane ${local.count}/${local.total}`, p: local.count / local.total };
}

export const variantsMore = (n) => `+${n} ${plural(n, "wariant", "warianty", "wariantów")}`;
