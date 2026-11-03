/**
 * Entry point of the interface: start the browser session, then show the
 * shell. Local mode (A-ADR-012): the session comes from the address
 * `archiwista serve` opened (`#token=…`, removed at once) or from the session
 * cookie; without one — or when it ends — the page says how to open a new
 * one. A token address pasted into an open tab changes only the fragment, so
 * it starts a session too. Team mode (ADR-046): without a session, or when it
 * ends, the sign-in page (views/login.js); a session signed in with a
 * temporary password changes it before the shell opens.
 */

import { onSessionLost, sessionMethods, startSession } from "./api.js";
import { SessionScreen, Shell } from "./shell.js";
import { html, render } from "./ui.js";
import { SignIn, TemporaryPassword } from "./views/login.js";

const root = document.getElementById("app");

function start() {
  startSession().then(open, (error) => {
    if (!error.problem) throw error;
    withoutSession(error.problem);
  });
}

/**
 * Show the shell of a session; one signed in with a temporary password
 * changes it first.
 *
 * @param {import("./types.js").SessionState} session
 */
function open(session) {
  const signedOut = () => withoutSession(null);
  if (session.password_change_required) {
    render(
      html`<${TemporaryPassword} session=${session} onChanged=${open} onSignOut=${signedOut} />`,
      root,
    );
  } else {
    render(html`<${Shell} session=${session} onSessionChange=${open} onSignOut=${signedOut} />`, root);
  }
}

/**
 * Without a session: the sign-in page of a team server, else how to open a
 * session of this computer — or why the server does not answer.
 *
 * @param {import("./types.js").Problem|null} problem - Why there is no
 *   session; `null` once a person of a team server signed out.
 * @param {boolean} [lost] - The session of this tab has ended.
 */
async function withoutSession(problem, lost = false) {
  let methods;
  try {
    methods = await sessionMethods();
  } catch (error) {
    if (!error.problem) throw error;
    render(html`<${SessionScreen} problem=${error.problem} lost=${lost} />`, root);
    return;
  }
  if (methods.mode === "team") {
    render(html`<${SignIn} methods=${methods} lost=${lost} onSignedIn=${open} />`, root);
  } else {
    render(html`<${SessionScreen} problem=${problem} lost=${lost} />`, root);
  }
}

onSessionLost((problem) => withoutSession(problem, true));
window.addEventListener("hashchange", () => {
  if (new URLSearchParams(location.hash.slice(1)).has("token")) start();
});
start();
