/**
 * Polish formatting of values for people (docs/SPEC.md 6.1, A-ADR-016): dates
 * `RRRR.MM.DD` in the interface while the API and files keep ISO, numbers
 * `12 345`, sizes in MB and GB, plural forms of counted words. Version labels
 * such as `2025-04-26_82710` are identifiers and are never reformatted.
 */

const INT = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 0 });
const ONE = new Intl.NumberFormat("pl-PL", {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});
const CLOCK = new Intl.DateTimeFormat("en-GB", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;
const EMPTY = "–";

function parts(date) {
  return Object.fromEntries(CLOCK.formatToParts(date).map((p) => [p.type, p.value]));
}

/**
 * A date as `RRRR.MM.DD`.
 *
 * @param {string|null|undefined} iso - `2026-10-18`, or a timestamp shown as
 *   the local date of this computer.
 * @returns {string} The date, or a dash when there is none.
 */
export function day(iso) {
  if (!iso) return EMPTY;
  if (DATE_ONLY.test(iso)) return iso.replaceAll("-", ".");
  const p = parts(new Date(iso));
  return `${p.year}.${p.month}.${p.day}`;
}

/**
 * A timestamp as `RRRR.MM.DD GG:MM` in this computer's time zone.
 *
 * @param {string|null|undefined} iso - ISO 8601 timestamp from the API.
 * @returns {string} The local time, or a dash when there is none.
 */
export function stamp(iso) {
  if (!iso) return EMPTY;
  const p = parts(new Date(iso));
  return `${p.year}.${p.month}.${p.day} ${p.hour}:${p.minute}`;
}

/**
 * A whole number with Polish digit grouping, e.g. `12 345`.
 *
 * @param {number|null|undefined} n
 * @returns {string}
 */
export function int(n) {
  return n === null || n === undefined ? EMPTY : INT.format(n);
}

/**
 * A size in MB, GB or TB (decimal units), e.g. `37,8 MB`.
 *
 * @param {number|null|undefined} bytes
 * @returns {string}
 */
export function size(bytes) {
  if (bytes === null || bytes === undefined) return EMPTY;
  if (bytes >= 1e12) return `${ONE.format(bytes / 1e12)} TB`;
  if (bytes >= 1e9) return `${ONE.format(bytes / 1e9)} GB`;
  return `${ONE.format(bytes / 1e6)} MB`;
}

/**
 * The Polish form of a word for a count.
 *
 * @param {number} n - Count.
 * @param {string[]} forms - `[one, few, many]`, e.g. `["kampania", "kampanie",
 *   "kampanii"]`.
 * @returns {string} The form only: `plural(5, forms)` is `"kampanii"`.
 */
export function plural(n, [one, few, many]) {
  if (n === 1) return one;
  const units = n % 10;
  const tens = n % 100;
  if (units >= 2 && units <= 4 && !(tens >= 12 && tens <= 14)) return few;
  return many;
}

/**
 * A count with its word, e.g. `count(2, forms)` is `"2 kampanie"`.
 *
 * @param {number} n
 * @param {string[]} forms - `[one, few, many]`.
 * @returns {string}
 */
export function count(n, forms) {
  return `${int(n)} ${plural(n, forms)}`;
}
