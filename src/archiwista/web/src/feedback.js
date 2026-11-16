/**
 * „Zgłoś uwagę” (Hydrograf's feedback; docs/SPEC.md 6.5 and 9.2): the top
 * bar's button opens a window where a person describes a fault or an idea
 * (a counter of its 5,000 characters), may leave a name or an e-mail address
 * and attaches the diagnostics unless they uncheck them. „Pokaż co zostanie
 * wysłane” shows exactly what is sent: the snapshot taken when the window
 * opened (diagnostics.js). „Wyślij” keeps the report (`POST /feedback`),
 * thanks the person and closes the window 2 s later; „Anuluj” and `Esc`
 * close it. A blank description is refused here, any other refusal as the
 * server gives it. Every session may send one.
 */

import { submitFeedback } from "./api.js";
import { useApp } from "./context.js";
import { pageAddress, snapshot } from "./diagnostics.js";
import { feedback as L } from "./labels/feedback.js";
import { t } from "./labels/index.js";
import {
  html,
  Icon,
  loadStylesheet,
  Modal,
  ProblemView,
  useEffect,
  useId,
  useRef,
  useState,
} from "./ui.js";

/** Hydrograf's limits, as `POST /feedback` checks them. */
const MESSAGE_MAX = 5000;
const CONTACT_MAX = 200;
const PAGE_URL_MAX = 500;
/** How long the thanks stay before the window closes. */
const CLOSE_AFTER_MS = 2000;

/** The top bar's „Zgłoś uwagę”; on a phone its icon alone. */
export function FeedbackButton() {
  const [open, setOpen] = useState(false);
  const button = useRef(null);
  useEffect(() => {
    loadStylesheet(new URL("./feedback.css", import.meta.url));
  }, []);
  const close = () => {
    setOpen(false);
    button.current?.focus();
  };
  return html`<button type="button" ref=${button} class="btn sm feedback-trigger"
      aria-haspopup="dialog"
      title=${L.button_title} aria-label=${L.button} onClick=${() => setOpen(true)}>
      <${Icon} name="message" size=${15} /><span class="feedback-trigger-text">${L.button}</span>
    </button>
    ${open ? html`<${FeedbackDialog} onClose=${close} />` : null}`;
}

/**
 * The window of a report.
 *
 * @param {{onClose: () => void}} props
 */
function FeedbackDialog({ onClose }) {
  const { health, session } = useApp();
  const [diagnostics] = useState(() =>
    snapshot({ version: health?.archiwista ?? null, mode: session.team ? "team" : "local" }),
  );
  const [text, setText] = useState("");
  const [contact, setContact] = useState("");
  const [attach, setAttach] = useState(true);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [empty, setEmpty] = useState(false);
  const [problem, setProblem] = useState(null);
  const field = useRef(null);
  const id = useId();
  useEffect(() => {
    field.current?.focus();
  }, []);
  useEffect(() => {
    if (!sent) return undefined;
    const timer = setTimeout(onClose, CLOSE_AFTER_MS);
    return () => clearTimeout(timer);
  }, [sent]);
  const send = async (event) => {
    event.preventDefault();
    const message = text.trim();
    setProblem(null);
    setEmpty(!message);
    if (!message) {
      field.current?.focus();
      return;
    }
    setBusy(true);
    try {
      await submitFeedback({
        message,
        contact: contact.trim() || null,
        page_url: pageAddress().slice(0, PAGE_URL_MAX),
        diagnostics: attach ? diagnostics : null,
      });
      setText("");
      setContact("");
      setSent(true);
    } catch (error) {
      if (!error.problem) throw error;
      setProblem(error.problem);
    } finally {
      setBusy(false);
    }
  };
  return html`<${Modal} label=${L.dialog.title} onClose=${onClose}>
    <form class="feedback-form" onSubmit=${send} novalidate>
      <h2>${L.dialog.title}</h2>
      <p>${L.dialog.intro}</p>
      <div class="field">
        <label for=${`${id}-message`}>${L.dialog.message}</label>
        <textarea id=${`${id}-message`} ref=${field} rows="6" maxlength=${MESSAGE_MAX}
          placeholder=${L.dialog.placeholder} aria-describedby=${`${id}-count`} value=${text}
          onInput=${(event) => setText(event.currentTarget.value)}></textarea>
        <span class="feedback-counter tabular" id=${`${id}-count`}>
          ${t(L.dialog.counter, { count: text.length, max: MESSAGE_MAX })}</span>
      </div>
      <div class="field">
        <label for=${`${id}-contact`}>
          ${L.dialog.contact} <span class="muted">${L.dialog.optional}</span></label>
        <input id=${`${id}-contact`} type="text" maxlength=${CONTACT_MAX} value=${contact}
          onInput=${(event) => setContact(event.currentTarget.value)} />
      </div>
      <label class="check-field feedback-check">
        <input type="checkbox" checked=${attach}
          onChange=${(event) => setAttach(event.currentTarget.checked)} />
        <span>${L.dialog.diagnostics}</span>
      </label>
      ${attach
        ? html`<details class="feedback-preview">
            <summary>${L.dialog.preview}</summary>
            <pre tabindex="0">${JSON.stringify(diagnostics, null, 2)}</pre>
          </details>`
        : null}
      ${empty ? html`<p class="feedback-status bad" role="status">${L.dialog.empty}</p>` : null}
      ${sent ? html`<p class="feedback-status ok" role="status">${L.dialog.sent}</p>` : null}
      ${problem ? html`<${ProblemView} problem=${problem} compact />` : null}
      <div class="modal-actions">
        <button type="button" class="btn" onClick=${onClose}>${L.dialog.cancel}</button>
        <button type="submit" class="btn primary" disabled=${busy || sent}>${L.dialog.send}</button>
      </div>
    </form>
  </${Modal}>`;
}
