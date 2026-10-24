/**
 * Sheet grids a person can show on the map (`GET /map/sheets`, docs/SPEC.md
 * 5.4): Kartograf's systems and scales, as its `find_sheets_for_bbox`
 * documents them. The server computes every sheet; an unknown system or
 * scale is its `422 kartograf_error`, shown as the producer says it.
 */

/** Scales of each Kartograf sheet system, coarse to fine. */
export const SHEET_GRIDS = {
  1992: ["1:1000000", "1:500000", "1:200000", "1:100000", "1:50000", "1:25000", "1:10000", "1:5000"],
  2000: ["1:10000", "1:5000", "1:2000", "1:1000", "1:500"],
};

/** The grid shown when a person turns it on. */
export const DEFAULT_GRID = { system: "1992", scale: "1:10000" };

/** The producer whose sheet grid is drawn. */
export const GRID_PRODUCER = "kartograf";

/**
 * A scale for people, e.g. `1:10 000`.
 *
 * @param {string} scale - E.g. `1:10000`.
 * @returns {string}
 */
export function scaleLabel(scale) {
  const [one, denominator] = scale.split(":");
  const number = Number(denominator);
  return Number.isFinite(number) ? `${one}:${new Intl.NumberFormat("pl-PL").format(number)}` : scale;
}
