/**
 * The year type of the station views (docs/SPEC.md 6.7, P15; plan I8.2 and
 * I8.5, ADR-045 decisions 3 and 10): the address's `year_type`, else the type
 * remembered for the data's family, else the family's default (hydrological
 * for hydro data, calendar for meteo data). A choice goes to the address; an
 * administrator's is also remembered for the family (`PUT
 * /settings/year-types`). The Catalog's filter panel and the station card's
 * header switch it.
 */

import { putYearTypes } from "../api.js";
import { useApp } from "../context.js";
import { useState } from "../ui.js";

/** The role that may change the settings, so remember a year type (`settings.write`). */
const ADMIN_ROLE = "admin";
/** The year types, in the order of the switch. */
export const YEAR_TYPES = ["hydrological", "calendar"];

/**
 * The year type in effect and how to choose another.
 *
 * @param {string|null|undefined} asked - `year_type` of the address.
 * @param {"hydro"|"meteo"} family - The family whose remembered type applies.
 * @param {(patch: {year_type: string}) => void} onChange - Writes the choice to
 *   the address.
 * @returns {{value: string, choose: (next: string) => void, admin: boolean,
 *   failed: boolean}} `admin`: the choice is remembered too; `failed`: the
 *   last one could not be.
 */
export function useYearType(asked, family, onChange) {
  const app = useApp();
  const [failed, setFailed] = useState(false);
  const remembered = app.settings?.year_types ?? null;
  const fallback = family === "hydro" ? "hydrological" : "calendar";
  const value = asked ?? remembered?.[family] ?? fallback;
  const admin = Boolean(app.session?.roles.includes(ADMIN_ROLE));
  const choose = (next) => {
    setFailed(false);
    onChange({ year_type: next });
    if (!admin || !remembered || remembered[family] === next) return;
    putYearTypes({ ...remembered, [family]: next }).then(app.setSettings, () => setFailed(true));
  };
  return { value, choose, admin, failed };
}
