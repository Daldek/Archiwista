/**
 * The year type of the station views (docs/SPEC.md 6.7, P15; plan I8.2 and
 * I8.5, ADR-045 decisions 3 and 10, ADR-047 erratum 1): the address's
 * `year_type`, else the type the person remembers for the data's family (their
 * preferences), else the family's default (hydrological for hydro data,
 * calendar for meteo data). A choice goes to the address and is remembered for
 * the family in the person's preferences (`PUT /preferences`). The Catalog's
 * filter panel and the station card's header switch it.
 */

import { useApp } from "../context.js";
import { useState } from "../ui.js";

/** The year types, in the order of the switch. */
export const YEAR_TYPES = ["hydrological", "calendar"];

/**
 * The year type in effect and how to choose another.
 *
 * @param {string|null|undefined} asked - `year_type` of the address.
 * @param {"hydro"|"meteo"} family - The family whose remembered type applies.
 * @param {(patch: {year_type: string}) => void} onChange - Writes the choice to
 *   the address.
 * @returns {{value: string, choose: (next: string) => void, failed: boolean}}
 *   `failed`: the last choice could not be remembered.
 */
export function useYearType(asked, family, onChange) {
  const app = useApp();
  const [failed, setFailed] = useState(false);
  const remembered = app.preferences?.year_types ?? null;
  const fallback = family === "hydro" ? "hydrological" : "calendar";
  const value = asked ?? remembered?.[family] ?? fallback;
  const choose = (next) => {
    setFailed(false);
    onChange({ year_type: next });
    if ((remembered?.[family] ?? fallback) === next) return;
    const remember = (current) => ({ year_types: { ...current.year_types, [family]: next } });
    app.savePreferences(remember).catch(() => setFailed(true));
  };
  return { value, choose, failed };
}
