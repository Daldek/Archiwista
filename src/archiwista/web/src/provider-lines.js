/**
 * The lines the data providers' terms require with their data (Nogat DEV §20,
 * A-ADR-055): an answer's `attribution`, then its `terms_notice`, each line
 * exactly as the API gives it — never paraphrased, translated or cut — under
 * „Źródło danych i warunki”, visible wherever the data are, never in a tooltip
 * or a folded panel. An address in a line to another computer is a link
 * whose text is the address (a line may be a sidecar's, from the store).
 * The station card and its chart, the comparison of stations, the Catalog's
 * lists of files and stations, the map's stations, the file card and the
 * comparison of versions show them; without lines nothing shows. The
 * comparison's CSV carries them in its last two columns (`lineColumns`).
 */

import { providerLines as L } from "./labels/provider-lines.js";
import { html, loadStylesheet, outsideLink, useId } from "./ui.js";
import { CopyAction, loadCardStyles } from "./views/cards.js";

await Promise.all([
  loadCardStyles(),
  loadStylesheet(new URL("./provider-lines.css", import.meta.url)),
]);

/** The lines of an answer without data of a provider whose terms are known. */
export const NO_LINES = Object.freeze({ attribution: [], terms_notice: [] });
/** The CSV columns of the lines (DEV-20.5), named as the API's fields. */
export const LINE_COLUMNS = ["attribution", "terms_notice"];
// An address in a line, without the punctuation that ends its sentence or parenthesis.
const ADDRESS = /https?:\/\/[^\s()<>]*[^\s()<>.,;:!?]/g;

/**
 * The lines of an answer: its `attribution` and `terms_notice`, none without them.
 *
 * @param {Partial<import("./types.js").ProviderLines>|null|undefined} answer
 * @returns {import("./types.js").ProviderLines}
 */
function linesOf(answer) {
  return { attribution: answer?.attribution ?? [], terms_notice: answer?.terms_notice ?? [] };
}

/**
 * The lines of an answer under „Źródło danych i warunki”: each line a
 * paragraph as the API gives it, the attribution first, then the terms;
 * nothing without lines.
 *
 * @param {object} props
 * @param {Partial<import("./types.js").ProviderLines>|null|undefined} props.answer - An
 *   answer of the API, or the lines of several (`mergeLines`).
 * @param {boolean} [props.copy] - With „Kopiuj atrybucję”: every line, one per line.
 * @param {boolean} [props.strip] - A strip under a list or a map: the heading beside
 *   the lines, which run on.
 * @param {3|4} [props.level] - The heading's level.
 * @param {string} [props.className] - The place's own classes.
 */
export function ProviderLines({ answer, copy = false, strip = false, level = 4, className = "" }) {
  const id = useId();
  const { attribution, terms_notice: terms } = linesOf(answer);
  if (!attribution.length && !terms.length) return null;
  const Heading = `h${level}`;
  const classes = ["provider-lines", strip ? "strip" : "", className].filter(Boolean).join(" ");
  const text = [...attribution, ...terms].join("\n");
  return html`<div class=${classes} role="group" aria-labelledby=${id}>
    <${Heading} class="section-title pl-title" id=${id}>${L.title}</${Heading}>
    <${Lines} lines=${attribution} />
    <${Lines} lines=${terms} terms />
    ${copy ? html`<${CopyAction} text=${text} label=${L.copy} />` : null}
  </div>`;
}

/** The lines of one kind, each a paragraph; nothing without them. */
function Lines({ lines, terms = false }) {
  if (!lines.length) return null;
  return html`<div class=${terms ? "pl-lines pl-terms" : "pl-lines"}>
    ${lines.map((line) => html`<p class="pl-line" key=${line}>${linked(line)}</p>`)}
  </div>`;
}

/** A line as text, each outside address in it a link whose text is the address. */
function linked(line) {
  const parts = [];
  let last = 0;
  for (const match of line.matchAll(ADDRESS)) {
    const target = outsideLink(match[0]);
    if (target === null) continue;
    if (match.index > last) parts.push(line.slice(last, match.index));
    parts.push(html`<a key=${match.index} href=${target} target="_blank"
      rel="noopener noreferrer">${match[0]}</a>`);
    last = match.index + match[0].length;
  }
  if (last < line.length) parts.push(line.slice(last));
  return parts;
}

/**
 * The lines of several answers shown together (the pages of a list): each
 * line once, a line new to the others placed among them as its own answer
 * orders it.
 *
 * @param {Array<Partial<import("./types.js").ProviderLines>|null|undefined>} parts
 * @returns {import("./types.js").ProviderLines}
 */
export function mergeLines(parts) {
  const all = parts.map(linesOf);
  return {
    attribution: merged(all.map((part) => part.attribution)),
    terms_notice: merged(all.map((part) => part.terms_notice)),
  };
}

/**
 * Lists of lines as one: a line new to the others follows the line before it
 * in its own list, else precedes the next of its list already placed, else
 * comes last.
 */
function merged(lists) {
  const found = [];
  for (const lines of lists) {
    let at = null;
    lines.forEach((line, index) => {
      const known = found.indexOf(line);
      if (known >= 0) {
        at = known + 1;
        return;
      }
      if (at === null) {
        const next = lines.slice(index + 1).find((later) => found.includes(later));
        at = next === undefined ? found.length : found.indexOf(next);
      }
      found.splice(at, 0, line);
      at += 1;
    });
  }
  return found;
}

/**
 * The cells of the lines' columns (`LINE_COLUMNS`) of a table of `rows` data
 * rows (DEV-20.5): one line per cell from the first row down, empty below; a
 * table with fewer rows than lines joins the rest into its last cell with a
 * newline.
 *
 * @param {Partial<import("./types.js").ProviderLines>|null|undefined} answer
 * @param {number} rows
 * @returns {string[][]|null} The two cells of each row; null without lines.
 */
export function lineColumns(answer, rows) {
  const { attribution, terms_notice: terms } = linesOf(answer);
  if (!attribution.length && !terms.length) return null;
  const cell = (lines, index) =>
    index < rows - 1 ? (lines[index] ?? "") : lines.slice(index).join("\n");
  return Array.from({ length: rows }, (_, index) => [
    cell(attribution, index),
    cell(terms, index),
  ]);
}
