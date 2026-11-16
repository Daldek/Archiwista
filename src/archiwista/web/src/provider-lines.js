/**
 * The lines the data providers' terms require with their data (Nogat DEV §20,
 * DEV-20.5, A-ADR-055): an answer's `attribution`, then its `terms_notice`,
 * each line exactly as the API gives it. On screen a view or a card has one
 * strip, the kit's `<nogat-sources>` (nogat/nogat-sources.js): 12 px, the
 * lines S, P, PS, PP and the short ČHMÚ line CK, then „Źródła i warunki”,
 * which opens a dialog with every line and the terms, and there „Kopiuj
 * atrybucję” (every line, one a line). The shell gives each view and each
 * overlay a `SourcesScope`; its parts report their answers' lines with
 * `useProviderLines` and its `SourcesStrip` shows them merged: the station
 * card with its chart, the comparison of stations, the Catalog's lists of
 * files and stations (with the map beside them), the map's stations, the
 * file card and the comparison of versions. Without lines nothing shows.
 * The comparison's CSV carries them in full in its last two columns
 * (`lineColumns`).
 */

import "../nogat/nogat-sources.js";
import { providerLines as L } from "./labels/provider-lines.js";
import {
  createContext,
  html,
  loadStylesheet,
  render,
  useCallback,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "./ui.js";
import { CopyAction, loadCardStyles } from "./views/cards.js";

await Promise.all([
  loadCardStyles(),
  loadStylesheet(new URL("./provider-lines.css", import.meta.url)),
]);

/** The lines of an answer without data of a provider whose terms are known. */
export const NO_LINES = Object.freeze({ attribution: [], terms_notice: [] });
/** The CSV columns of the lines (DEV-20.5), named as the API's fields. */
export const LINE_COLUMNS = ["attribution", "terms_notice"];

/** The scope of a view or an overlay: `report(key, lines)` and the merged `lines`. */
const Scope = createContext(null);

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
 * One view's or overlay's lines: what its parts report, merged in the order
 * they first reported, for its one `SourcesStrip`.
 *
 * @param {{children: unknown}} props
 */
export function SourcesScope({ children }) {
  const [parts, setParts] = useState(() => new Map());
  const report = useCallback(
    (key, lines) =>
      setParts((previous) => {
        const next = new Map(previous);
        if (lines) next.set(key, lines);
        else next.delete(key);
        return next;
      }),
    [],
  );
  const value = useMemo(() => ({ report, lines: mergeLines([...parts.values()]) }), [report, parts]);
  return html`<${Scope.Provider} value=${value}>${children}</${Scope.Provider}>`;
}

/**
 * Report an answer's lines to the scope's strip while the part is shown;
 * none (`null`) while its data are not on screen.
 *
 * @param {Partial<import("./types.js").ProviderLines>|null|undefined} answer - An
 *   answer of the API, or the lines of several (`mergeLines`).
 */
export function useProviderLines(answer) {
  const report = useContext(Scope)?.report;
  const key = useId();
  const lines = linesOf(answer);
  const text = JSON.stringify(lines);
  // Before the paint, so the strip appears with the data and does not move the view after.
  useLayoutEffect(() => {
    report?.(key, lines.attribution.length || lines.terms_notice.length ? lines : null);
  }, [report, key, text]);
  useLayoutEffect(() => () => report?.(key, null), [report, key]);
}

/**
 * The one strip of a view or an overlay: `<nogat-sources>` with the scope's
 * lines, and „Kopiuj atrybucję” in its dialog; hidden without lines. Esc in
 * the dialog closes it only.
 */
export function SourcesStrip() {
  const lines = useContext(Scope)?.lines ?? NO_LINES;
  const element = useRef(null);
  const text = useRef("");
  const shown = JSON.stringify(lines);
  text.current = [...lines.attribution, ...lines.terms_notice].join("\n");
  useLayoutEffect(() => {
    // Set once per change, before the browser paints: the element draws its strip and
    // dialog again, and the view's layout does not shift a frame later.
    element.current.attribution = lines.attribution;
    element.current.termsNotice = lines.terms_notice;
  }, [shown]);
  useEffect(() => {
    const node = element.current;
    const open = () => {
      const content = node.querySelector("dialog .nogat-sources-content");
      if (!content) return;
      let place = content.querySelector(":scope > .sources-copy");
      if (!place) {
        place = document.createElement("p");
        place.className = "sources-copy";
        content.append(place);
      }
      render(html`<${CopyAction} text=${text.current} label=${L.copy} />`, place);
    };
    // Esc closes the dialog only, not the card or the overlay under it (shell.js).
    const key = (event) => {
      if (event.key === "Escape" && node.isOpen) event.stopPropagation();
    };
    node.addEventListener("nogat-sources-open", open);
    node.addEventListener("keydown", key);
    return () => {
      node.removeEventListener("nogat-sources-open", open);
      node.removeEventListener("keydown", key);
    };
  }, []);
  return html`<nogat-sources class="view-sources" ref=${element}></nogat-sources>`;
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
