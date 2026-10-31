/**
 * A project's activity on its card (A-ADR-049 decision 14): from the action
 * log, what was done to the project — created, changed, shared, pinned,
 * unpinned, exported — and the jobs started, retried or cancelled for it,
 * done or failed, newest first: the 20 newest, „Więcej” for older ones. Each
 * entry says when, who (a person's name, their agent, the scheduler) and
 * what, with the group, the export or the kind of job it was about. Whoever
 * sees the project sees its activity; the client address and the session
 * stay in „Dziennik” for administrators.
 */

import { getProjectActivity } from "../api.js";
import { stamp } from "../format.js";
import { useResource } from "../hooks.js";
import { activity as L } from "../labels/activity.js";
import { T, t } from "../labels/index.js";
import { log as LOG } from "../labels/log.js";
import { html, ProblemView, Spinner, useEffect, useId, useState } from "../ui.js";
import { actorName, Badge } from "./cards.js";

/** Entries of the first page and of each „Więcej”. */
const PAGE = 20;

/**
 * The activity of a project.
 *
 * @param {{card: import("../types.js").ProjectCard}} props - The project's card;
 *   the activity is read again when the index read the project again.
 */
export function ProjectActivity({ card }) {
  const id = useId();
  const first = useResource(
    (signal) => getProjectActivity(card.project, { limit: PAGE }, { signal }),
    [card.project, card.scanned_at],
  );
  const [extra, setExtra] = useState({ items: [], cursor: null, loading: false, problem: null });
  const page = first.data;
  useEffect(
    () => setExtra({ items: [], cursor: page?.next_cursor ?? null, loading: false, problem: null }),
    [page],
  );
  const more = async () => {
    setExtra((current) => ({ ...current, loading: true, problem: null }));
    try {
      const next = await getProjectActivity(card.project, { limit: PAGE, cursor: extra.cursor });
      setExtra((current) => ({
        items: [...current.items, ...next.items],
        cursor: next.next_cursor,
        loading: false,
        problem: null,
      }));
    } catch (error) {
      if (!error.problem) throw error;
      setExtra((current) => ({ ...current, loading: false, problem: error.problem }));
    }
  };
  const items = page ? [...page.items, ...extra.items] : [];
  return html`<section class="det-sec" aria-labelledby=${`${id}-title`}>
    <h3 class="section-title" id=${`${id}-title`}>${L.title}</h3>
    ${first.error ? html`<${ProblemView} problem=${first.error.problem} compact />` : null}
    ${page === undefined && !first.error ? html`<${Spinner} />` : null}
    ${page && !items.length ? html`<p class="faint">${L.empty}</p>` : null}
    ${items.length
      ? html`<ol class="pc-activity" aria-label=${L.list}>
          ${items.map((entry) => html`<${Entry} key=${entry.id} entry=${entry} />`)}
        </ol>`
      : null}
    ${extra.cursor
      ? html`<button type="button" class="btn sm" title=${L.more_title} disabled=${extra.loading}
          onClick=${more}>${L.more}</button>`
      : null}
    ${extra.problem ? html`<${ProblemView} problem=${extra.problem} compact />` : null}
  </section>`;
}

/** An entry: when, who, what and about what; a failure marked. */
function Entry({ entry }) {
  const what = LOG.actions[entry.action] ?? entry.action;
  const about = subject(entry);
  return html`<li class="pc-activity-entry">
    <span class="faint tabular">${stamp(entry.at)}</span>
    <span><b>${who(entry)}</b> ${about ? `${what}, ${about}` : what}</span>
    ${entry.outcome === "failed" ? html`<${Badge} level="bad">${LOG.outcomes.failed}</${Badge}>` : null}
  </li>`;
}

/** Who acted: a person's name (or account), their agent, the scheduler, the computer's owner. */
function who(entry) {
  if (entry.actor_kind === "scheduler") return LOG.actor.scheduler;
  const name = entry.actor_name ?? actorName(entry.actor);
  return entry.actor_kind === "agent" ? t(LOG.actor.agent, { actor: name }) : name;
}

/** What an entry was about: a group of pins, an export, the kind of a job; `null` otherwise. */
function subject(entry) {
  const details = entry.details ?? {};
  if (entry.action.startsWith("job.")) {
    return T.common.job_kind[details.kind] ?? details.kind ?? null;
  }
  if (entry.action === "project.export" && details.name) return t(L.export, { name: details.name });
  if (details.group) return t(L.group, { group: details.group });
  return null;
}
