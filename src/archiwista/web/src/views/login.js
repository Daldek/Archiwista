/**
 * Signing in to a team server (docs/SPEC.md 6.5 n, ADR-046): the account and
 * its password with „Pokaż”, one message for every refused account, the
 * wait after failed attempts counted down (`429`, `details.retry_after_s`),
 * „Zaloguj kontem firmowym” when the company's trusted proxy names the
 * person, and the change of a password — a temporary one before the shell
 * opens. The fields keep the browser's password manager working
 * (`autocomplete`) and allow pasting (ASVS 6.2.6, 6.2.7).
 */

import { changePassword, endSession, proxySignIn, signIn } from "../api.js";
import { account as L } from "../labels/account.js";
import { T, t } from "../labels/index.js";
import { html, loadStylesheet, Logo, ProblemView, useEffect, useId, useState } from "../ui.js";

await loadStylesheet(new URL("./login.css", import.meta.url));

/**
 * The sign-in page of a team server.
 *
 * @param {{methods: import("../types.js").SessionMethods, lost?: boolean,
 *   onSignedIn: (session: import("../types.js").NewSession) => void}} props -
 *   `lost`: the previous session ended.
 */
export function SignIn({ methods, lost, onSignedIn }) {
  const id = useId();
  const [form, setForm] = useState({ account: "", password: "" });
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState(null);
  const [left, wait] = useWait();
  const ready = form.account.trim() !== "" && form.password !== "" && !busy && left === 0;
  const attempt = async (start) => {
    setBusy(true);
    setProblem(null);
    try {
      onSignedIn(await start());
    } catch (error) {
      if (!error.problem) throw error;
      waitIfBlocked(error.problem, wait);
      setProblem(error.problem);
      setBusy(false);
    }
  };
  const submit = (event) => {
    event.preventDefault();
    if (ready) attempt(() => signIn(form.account, form.password));
  };
  const change = (patch) => setForm((now) => ({ ...now, ...patch }));
  return html`<div class="session-screen">
    <form class="session-card sign-in" aria-labelledby=${`${id}-title`} onSubmit=${submit}>
      <div class="brand"><${Logo} /><span>${T.shell.brand}</span>
        <span class="sign-in-host">${location.host}</span></div>
      <h1 id=${`${id}-title`}>${L.sign_in.title}</h1>
      ${lost ? html`<p class="session-detail" role="status">${L.sign_in.lost}</p>` : null}
      <div class="field">
        <label for=${`${id}-account`}>${L.sign_in.account}</label>
        <input id=${`${id}-account`} name="username" autocomplete="username"
          autocapitalize="none" spellcheck="false" value=${form.account}
          onInput=${(event) => change({ account: event.currentTarget.value })} />
      </div>
      <${PasswordField} id=${`${id}-password`} label=${L.sign_in.password}
        autocomplete="current-password" value=${form.password}
        onInput=${(password) => change({ password })} />
      <${Refusal} problem=${problem} left=${left} />
      <button type="submit" class="btn primary block" disabled=${!ready}>${L.sign_in.submit}</button>
      ${methods.proxy
        ? html`<div class="sign-in-alt">
            <button type="button" class="btn block" disabled=${busy || left > 0}
              onClick=${() => attempt(proxySignIn)}>${L.sign_in.proxy}</button>
            <span class="field-hint">${L.sign_in.proxy_hint}</span>
          </div>`
        : null}
      <p class="field-hint">${L.sign_in.forgot}</p>
    </form>
  </div>`;
}

/**
 * The page of a session signed in with a temporary password: the password
 * is changed before anything else, or the person signs out.
 *
 * @param {{session: import("../types.js").SessionState,
 *   onChanged: (session: import("../types.js").NewSession) => void,
 *   onSignOut: () => void}} props
 */
export function TemporaryPassword({ session, onChanged, onSignOut }) {
  const signOut = () => endSession().catch(() => null).then(onSignOut);
  return html`<div class="session-screen">
    <div class="session-card password-screen">
      <div class="brand"><${Logo} /><span>${T.shell.brand}</span>
        <span class="sign-in-host">${location.host}</span></div>
      <${PasswordChange} session=${session} temporary onChanged=${onChanged} onCancel=${signOut} />
    </div>
  </div>`;
}

/**
 * The change of the session's password: the current one, the new one twice.
 *
 * @param {{session: import("../types.js").SessionState, temporary?: boolean,
 *   onChanged: (session: import("../types.js").NewSession) => void,
 *   onCancel: () => void}} props - `temporary`: the change before the shell
 *   opens, whose other way out is signing out.
 */
export function PasswordChange({ session, temporary, onChanged, onCancel }) {
  const id = useId();
  const [form, setForm] = useState({ current: "", next: "", repeat: "" });
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState(null);
  const [left, wait] = useWait();
  const reason = problem?.details?.reason;
  const mismatch = form.repeat !== "" && form.repeat !== form.next;
  const ready =
    form.current !== "" && form.next !== "" && form.repeat === form.next && !busy && left === 0;
  const change = (patch) => {
    setForm((now) => ({ ...now, ...patch }));
    if (problem?.details?.reason !== "login_blocked") setProblem(null);
  };
  const submit = async (event) => {
    event.preventDefault();
    if (!ready) return;
    setBusy(true);
    setProblem(null);
    try {
      onChanged(await changePassword(form.current, form.next));
    } catch (error) {
      if (!error.problem) throw error;
      waitIfBlocked(error.problem, wait);
      setProblem(error.problem);
      setBusy(false);
    }
  };
  const title = `${temporary ? L.change.title_temporary : L.change.title} · ${session.actor}`;
  const fieldProblem = reason === "wrong_password" || reason === "password_policy";
  return html`<form class="password-change" aria-labelledby=${`${id}-title`} onSubmit=${submit}>
    ${temporary
      ? html`<h1 id=${`${id}-title`}>${title}</h1>
          <p class="session-detail">${L.change.temporary_note}</p>`
      : html`<h2 id=${`${id}-title`}>${title}</h2>`}
    <${PasswordField} id=${`${id}-current`} label=${L.change.current}
      autocomplete="current-password" value=${form.current}
      invalid=${reason === "wrong_password"}
      note=${reason === "wrong_password" ? problem.detail : null}
      onInput=${(current) => change({ current })} />
    <${PasswordField} id=${`${id}-new`} label=${L.change.new} autocomplete="new-password"
      value=${form.next} invalid=${reason === "password_policy"}
      note=${reason === "password_policy" ? problem.detail : L.change.rule}
      onInput=${(next) => change({ next })} />
    <${PasswordField} id=${`${id}-repeat`} label=${L.change.repeat} autocomplete="new-password"
      value=${form.repeat} invalid=${mismatch} note=${mismatch ? L.change.mismatch : null}
      onInput=${(repeat) => change({ repeat })} />
    ${fieldProblem ? null : html`<${Refusal} problem=${problem} left=${left} />`}
    <p class="field-hint">${L.change.ended}</p>
    <div class="password-change-actions">
      <button type="button" class="btn ghost" disabled=${busy} onClick=${onCancel}>
        ${temporary ? L.change.sign_out : L.change.cancel}</button>
      <button type="submit" class="btn primary" disabled=${!ready}>${L.change.submit}</button>
    </div>
  </form>`;
}

/**
 * A password input with „Pokaż”, which shows the typed password until
 * pressed again.
 *
 * @param {{id: string, label: string, autocomplete: string, value: string,
 *   onInput: (value: string) => void, note?: string|null, invalid?: boolean}} props
 */
function PasswordField({ id, label, autocomplete, value, onInput, note, invalid }) {
  const [shown, setShown] = useState(false);
  return html`<div class=${invalid ? "field invalid" : "field"}>
    <label for=${id}>${label}</label>
    <div class="password-row">
      <input id=${id} type=${shown ? "text" : "password"} autocomplete=${autocomplete}
        autocapitalize="none" spellcheck="false" value=${value}
        aria-invalid=${invalid ? "true" : null} aria-describedby=${note ? `${id}-note` : null}
        onInput=${(event) => onInput(event.currentTarget.value)} />
      <button type="button" class="btn sm" aria-pressed=${shown ? "true" : "false"}
        aria-controls=${id} title=${L.show_label} onClick=${() => setShown(!shown)}>${L.show}</button>
    </div>
    ${note
      ? html`<span id=${`${id}-note`} class=${invalid ? "field-error" : "field-hint"}
          role=${invalid ? "alert" : null}>${note}</span>`
      : null}
  </div>`;
}

/**
 * Why the last attempt was refused: the wait counted down, the server's one
 * message of a refused sign-in, or any other problem.
 *
 * @param {{problem: import("../types.js").Problem|null, left: number}} props
 */
function Refusal({ problem, left }) {
  if (problem === null) return null;
  const reason = problem.details?.reason;
  if (reason === "login_blocked") {
    return left > 0
      ? html`<p class="sign-in-message" role="alert">${t(L.sign_in.wait, { wait: waitText(left) })}</p>`
      : null;
  }
  if (reason === "login_failed" || reason === "password_expired") {
    return html`<p class="sign-in-message" role="alert">${problem.detail}</p>`;
  }
  return html`<${ProblemView} problem=${problem} compact />`;
}

/** Start the wait of a `429 login_blocked`; any other problem waits for nothing. */
function waitIfBlocked(problem, wait) {
  if (problem.details?.reason === "login_blocked") wait(Number(problem.details.retry_after_s) || 1);
}

/**
 * A wait counted down: the whole seconds left and a function starting one.
 *
 * @returns {[number, (seconds: number) => void]}
 */
function useWait() {
  const [until, setUntil] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (until <= Date.now()) return undefined;
    const timer = setInterval(() => {
      const moment = Date.now();
      setNow(moment);
      if (moment >= until) clearInterval(timer);
    }, 250);
    return () => clearInterval(timer);
  }, [until]);
  const start = (seconds) => {
    const moment = Date.now();
    setNow(moment);
    setUntil(moment + seconds * 1000);
  };
  return [Math.max(0, Math.ceil((until - now) / 1000)), start];
}

function waitText(seconds) {
  if (seconds < 60) return t(L.wait_seconds, { seconds });
  return t(L.wait_minutes, { minutes: Math.floor(seconds / 60), seconds: seconds % 60 });
}
