/**
 * A product's variant for people (A-ADR-017): its resolution and height
 * system in plain words, e.g. „1 m · EVRF2007”, „5 m · EVRF2007”,
 * „1 m · Kronsztadt 86”; the file format is never part of it. One name per
 * variant across the interface: the catalog's rows and its „Wariant” filter
 * (a store segment is one variant, keeping its own current version), the file
 * card, the map's variants of a product and the layers of the fan, the
 * timeline and the set's details. A product without variants (no resolution,
 * no height system) has no name.
 */

import { cards as C } from "./labels/cards.js";
import { t } from "./labels/index.js";
import { variant as L } from "./labels/variant.js";

const RESOLUTION = /^(\d+(?:[.,]\d+)?)\s*(cm|km|m)$/i;

/**
 * Facts of a variant as the index gives them.
 *
 * @typedef {object} VariantFacts
 * @property {string|null} [resolution] - E.g. `1m`.
 * @property {string|null} [horizontal_crs] - EPSG code.
 * @property {string|null} [vertical_crs] - EPSG code.
 */

/**
 * The facts of a row's version or of a product's segment: both carry
 * `resolution` and `crs`.
 *
 * @param {{resolution: string|null, crs: {horizontal: string|null, vertical: string|null}}|null} item
 * @returns {VariantFacts}
 */
export function variantFacts(item) {
  return {
    resolution: item?.resolution ?? null,
    horizontal_crs: item?.crs?.horizontal ?? null,
    vertical_crs: item?.crs?.vertical ?? null,
  };
}

/**
 * A resolution for people: `1m` → „1 m”, `0.25m` → „0,25 m”; another text
 * as it is.
 *
 * @param {string} value
 * @returns {string}
 */
export function resolutionName(value) {
  const match = RESOLUTION.exec(value.trim());
  return match ? `${match[1].replace(".", ",")} ${match[2].toLowerCase()}` : value;
}

/**
 * A height system for people, e.g. „Kronsztadt 86” for `EPSG:9650`.
 *
 * @param {string} code
 * @returns {string}
 */
export function heightName(code) {
  return L.heights[code] ?? C.crs[code] ?? t(L.height_unknown, { code });
}

/**
 * The name of a variant: its resolution and height system; with
 * `horizontal` the sheet system too (two variants of a list told apart).
 *
 * @param {VariantFacts} facts
 * @param {{horizontal?: boolean}} [options]
 * @returns {string|null} Null for a product without variants.
 */
export function variantName(facts, { horizontal = false } = {}) {
  const parts = [
    facts.resolution ? resolutionName(facts.resolution) : null,
    facts.vertical_crs ? heightName(facts.vertical_crs) : null,
    horizontal && facts.horizontal_crs ? (C.crs[facts.horizontal_crs] ?? facts.horizontal_crs) : null,
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : null;
}

/**
 * The name of a layer's variant (`LayerVariant`); a variant keyed by its
 * segments (a fact missing in the metadata) adds them.
 *
 * @param {import("./types.js").LayerVariant} variant
 * @param {{horizontal?: boolean}} [options] - As `variantName`.
 * @returns {string}
 */
export function layerVariantName(variant, options) {
  const name = variantName(variant, options);
  const complete = variant.resolution && variant.horizontal_crs && variant.vertical_crs;
  if (complete) return name;
  return [name, ...variant.segments].filter(Boolean).join(" · ") || L.no_meta;
}

/**
 * Distinct names of the variants of one list: a name two of them share
 * adds the sheet system, and a name still shared the fallback (a segment).
 *
 * @template T
 * @param {T[]} items
 * @param {(item: T, options: {horizontal: boolean}) => string|null} nameOf -
 *   `variantName` or `layerVariantName` of an item.
 * @param {(item: T, name: string|null) => string} fallbackOf - Tells apart
 *   what the facts do not; `name` is the item's name so far.
 * @returns {Map<T, string>}
 */
export function variantNames(items, nameOf, fallbackOf) {
  const shared = (names) => {
    const seen = new Map();
    for (const name of names.values()) seen.set(name, (seen.get(name) ?? 0) + 1);
    return (name) => name === null || seen.get(name) > 1;
  };
  const names = new Map(items.map((item) => [item, nameOf(item, { horizontal: false })]));
  const twice = shared(names);
  for (const item of items) {
    if (twice(names.get(item))) names.set(item, nameOf(item, { horizontal: true }));
  }
  const still = shared(names);
  for (const item of items) {
    const name = names.get(item);
    if (!still(name)) continue;
    const fallback = fallbackOf(item, name);
    names.set(item, name ? `${name} · ${fallback}` : fallback);
  }
  return names;
}

/**
 * Names of a product's variants by segment path (`GET /products`; a store
 * segment is one variant), each distinct: one shared by two variants adds
 * the segment, and a segment without variant facts is called by the
 * producer's name.
 *
 * @param {import("./types.js").Product} product
 * @returns {Map<string|null, string>}
 */
export function segmentVariantNames(product) {
  const first = new Map();
  for (const item of product.segments) {
    if (!first.has(item.segment.path)) first.set(item.segment.path, item);
  }
  const items = [...first.values()];
  const names = variantNames(
    items,
    (item, options) => variantName(variantFacts(item), options),
    (item, name) => (name ? (item.segment.path ?? item.segment.label) : item.segment.label),
  );
  return new Map(items.map((item) => [item.segment.path, names.get(item)]));
}
