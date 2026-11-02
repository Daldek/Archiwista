/**
 * Usable areas of the projects visible to this session, shared by the map,
 * catalog and source command. A changed or unread project area is never offered.
 */

import { listProjects } from "../api.js";
import { useResource } from "../hooks.js";
import { projects as L } from "../labels/projects.js";
import { html } from "../ui.js";

/**
 * @typedef {{project: string, name: string, area_id: string,
 *   project_write: boolean}} UsableProjectArea
 */

/** @returns {{items: UsableProjectArea[], error: *, loading: boolean, reload: () => void}} */
export function useProjectAreas() {
  const resource = useResource((signal) => listProjects({}, { signal }), []);
  return {
    ...resource,
    items: (resource.data?.items ?? [])
      .filter((item) => item.state === "ok" && item.area?.state === "ok" && item.area.area_id)
      .map((item) => ({
        project: item.project,
        name: item.name,
        area_id: item.area.area_id,
        project_write: item.project_write,
      })),
  };
}

/** @param {string|null} areaId @param {UsableProjectArea[]} projects */
export function projectsOfArea(areaId, projects) {
  return areaId ? projects.filter((item) => item.area_id === areaId) : [];
}

/** One project per option, even when several projects share the same area. */
export function ProjectAreaSelect({ projects, areaId, onChange }) {
  const chosen = projectsOfArea(areaId, projects)[0]?.project ?? "";
  return html`<label class="field">
    <span>${L.area_choice.label}</span>
    <select class="select-sm" value=${chosen} onChange=${(event) => {
      const item = projects.find((entry) => entry.project === event.currentTarget.value);
      onChange(item?.area_id ?? null);
    }}>
      <option value="">${L.area_choice.placeholder}</option>
      ${projects.map((item) => html`<option key=${item.project} value=${item.project}>
        ${item.name}</option>`)}
    </select>
  </label>`;
}
