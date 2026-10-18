/**
 * Products of the index for people (docs/SPEC.md 6.3, SPEC 13 criterion 6):
 * the producer's name of the product's main segment, with the product key
 * and the segments one click away. Nothing is guessed: a product exists only
 * when the index has a file of it.
 */

import { map as L } from "../labels/map.js";

/**
 * The name of a product: its biggest segment's name up to the variant
 * details (` · PL-1992 · EVRF2007`), e.g. „Numeryczny Model Terenu 1 m
 * (siatka ASC)” for `nmt`.
 *
 * @param {import("../types.js").Product} product
 * @returns {string}
 */
export function productTitle(product) {
  if (!product.product) return L.product.unknown;
  const main = [...product.segments].sort((a, b) => b.slots - a.slots)[0];
  return (main?.segment.label ?? product.product).split(" · ")[0];
}

/**
 * Names of products by key, for chips, tooltips and the local state.
 *
 * @param {import("../types.js").Product[]} products
 * @returns {Map<string, string>}
 */
export function productNames(products) {
  return new Map(
    products.filter((product) => product.product).map((product) => [product.product, productTitle(product)]),
  );
}

/**
 * Stores holding a product, in the order of the settings.
 *
 * @param {import("../types.js").Product} product
 * @param {string[]} stores - Store ids of the settings.
 * @returns {string[]}
 */
export function productStores(product, stores) {
  const holding = new Set(product.segments.map((segment) => segment.store));
  return stores.filter((store) => holding.has(store));
}
