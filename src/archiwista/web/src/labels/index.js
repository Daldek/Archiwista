/**
 * Dictionary of interface texts (Polish; docs/DEVELOPMENT_STANDARDS.md 4.3:
 * no text is typed into a component).
 *
 * The shared part is composed here: `common` (actions, states, units),
 * `shell` and `setup`. Each view keeps its own file `labels/<view>.js`
 * exporting one object and imports it directly, so views never edit a shared
 * file (docs/plans/2026-10-18-plan-v0.1.md, WWW contract). Texts are strings with `{name}`
 * placeholders filled by `t`; plural forms are `[one, few, many]` arrays
 * used with `count` of `format.js`.
 */

import { common } from "./common.js";
import { setup } from "./setup.js";
import { shell } from "./shell.js";

export const T = Object.freeze({ common, shell, setup });

/**
 * Fill the `{name}` placeholders of a text.
 *
 * @param {string} text - Text from a dictionary.
 * @param {Object<string, string|number>} [values] - Values by placeholder name;
 *   a placeholder without a value stays as it is.
 * @returns {string}
 */
export function t(text, values = {}) {
  return text.replace(/\{(\w+)\}/g, (whole, name) =>
    Object.hasOwn(values, name) ? String(values[name]) : whole,
  );
}
