// Coverage vocabulary (agreed with docs/SPEC.md 6.4) and Polish formatting.
// Dates in the interface: YYYY.MM.DD (user decision), e.g. "2023.06.04".

const NUM = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const INT = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 0 });
const ONE = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 1, minimumFractionDigits: 1 });
const STAMP = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Warsaw",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
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
export const mb = (bytes) => (bytes >= 1e9 ? `${ONE.format(bytes / 1e9)} GB` : `${INT.format(bytes / 1e6)} MB`);

/** ISO timestamp -> "2026.10.17 13:03" (Europe/Warsaw). */
export function stamp(iso) {
  const p = Object.fromEntries(STAMP.formatToParts(new Date(iso)).map((x) => [x.type, x.value]));
  return `${p.year}.${p.month}.${p.day} ${p.hour}:${p.minute}`;
}

/** "2024-06-21" -> "2024.06.21". */
export function day(iso) {
  if (!iso) return "–";
  return iso.slice(0, 10).replaceAll("-", ".");
}

/** Flight date span: "2025.04.28" or "2024.06.21–2024.07.30". */
export function span(pair) {
  if (!pair || !pair[0]) return "–";
  const [a, b] = pair;
  return !b || a === b ? day(a) : `${day(a)}–${day(b)}`;
}

/**
 * CLI equivalent of a report's download hints: the first command and, when
 * the report gives one command per sheet, a comment with the rest.
 */
export function hintText(hints, suffix = "") {
  const more = hints.length - 1;
  const rest = more > 0 ? `\n# + ${int(more)} ${plural(more, "polecenie", "polecenia", "poleceń")} dla kolejnych arkuszy` : "";
  return `kartograf ${hints[0]}${suffix}${rest}`;
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
export function coverage(c, { short = false } = {}) {
  if (!c) return { kind: "none", text: "brak danych" };
  // own data: no remote source, so no availability; snapshot or the working file against the last snapshot
  if (c.own) {
    if (!c.current) return { kind: "own", text: short ? "migawka" : `migawka · ${int(c.stats.count)} ${plural(c.stats.count, "obiekt", "obiekty", "obiektów")}` };
    return c.changedSince
      ? { kind: "changed", text: short ? "zmieniony" : `zmieniony od migawki ${day(c.changedSince.date)}` }
      : { kind: "own", text: short ? "bez zmian" : "bez zmian od ostatniej migawki" };
  }
  if (c.complete) {
    const n = c.campaignsSelected.length;
    if (n > 1) return { kind: "multi", text: `pełne · ${n} ${plural(n, "kampania", "kampanie", "kampanii")}`, campaigns: n };
    return { kind: "full", text: "pełne", campaigns: 1 };
  }
  const share = c.landM2 > 0 ? c.fullM2 / c.landM2 : 0;
  const pct = Math.floor(share * 100);
  let text = `częściowe · ${share > 0 && pct === 0 ? "<1" : pct}%`;
  const partial = c.sheetsPartial.length;
  if (partial && !short) text += ` · ${partial} ark. ${plural(partial, "niepełny", "niepełne", "niepełnych")}`;
  return { kind: "partial", text, pct: share * 100 };
}

/** Local store badge (docs/SPEC.md 6.4): "pobrane" / "pobrane 5/12" / "niepobrane". */
export function localBadge(local) {
  if (local?.own) return { kind: "done", text: "w folderze projektu" };
  if (!local || local.count === 0) return { kind: "no", text: "niepobrane" };
  if (local.count >= local.total) return { kind: "done", text: "pobrane" };
  return { kind: "some", text: `pobrane ${local.count}/${local.total}`, p: local.count / local.total };
}

export const variantsMore = (n) => `+${n} ${plural(n, "wariant", "warianty", "wariantów")}`;
