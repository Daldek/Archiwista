/**
 * Texts of a product's variant (variant.js): the names of height systems
 * and what a variant without facts is called. One name per variant across
 * the interface: the catalog's rows and its „Wariant” filter, the file card,
 * the map's variants and the layers.
 */

export const variant = {
  /** Height systems by the EPSG code of the index (Kartograf's codes). */
  heights: {
    "EPSG:9651": "EVRF2007",
    "EPSG:5621": "EVRF2007",
    "EPSG:9650": "Kronsztadt 86",
    "EPSG:8357": "Bpv (bałtycki po wyrównaniu)",
  },
  height_unknown: "układ wysokości {code}",
  /** A layer whose metadata names neither its variant nor its segment. */
  no_meta: "bez metadanych",
};
