/**
 * MapLibre GL JS 6 for map views, from the package (vendor/vendor.json): the
 * ES module, its stylesheet and local glyphs, never a CDN.
 *
 * The CSP allows only `worker-src 'self'` (no `blob:`): the module starts its
 * worker `maplibre-gl-worker.mjs` as a same-origin module worker, found next
 * to the module by its own URL. Map labels use `GLYPHS` with the font
 * `GLYPH_FONT` (Latin with its extensions, Cyrillic and punctuation), so a
 * map needs no external request — offline mode adds only the basemap rule.
 */

import { loadStylesheet } from "./ui.js";

const VENDOR = new URL("../vendor/", import.meta.url);

/** Style `glyphs` address of the packaged fonts. */
export const GLYPHS = `${new URL("glyphs/", VENDOR).href}{fontstack}/{range}.pbf`;

/** The packaged font, for `text-font: [GLYPH_FONT]`. */
export const GLYPH_FONT = "noto-sans-regular";

let loading = null;

/**
 * Load MapLibre and its stylesheet once.
 *
 * @returns {Promise<typeof import("../vendor/maplibre-gl/maplibre-gl.mjs")>} The
 *   module namespace: `Map`, `NavigationControl`, `LngLatBounds`…
 */
export function loadMapLibre() {
  loading ??= Promise.all([
    import("../vendor/maplibre-gl/maplibre-gl.mjs"),
    loadStylesheet(new URL("maplibre-gl/maplibre-gl.css", VENDOR)),
  ]).then(
    ([maplibre]) => maplibre,
    (error) => {
      loading = null;
      throw error;
    },
  );
  return loading;
}
