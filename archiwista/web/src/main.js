/**
 * Entry point of the interface: start the browser session from the address
 * `archiwista serve` opened (`#token=…`, removed at once) or from the session
 * cookie, then show the shell; without a session — or when it ends — show
 * how to open a new one. A token address pasted into an open tab changes only
 * the fragment, so it starts a session too.
 */

import { onSessionLost, startSession } from "./api.js";
import { SessionScreen, Shell } from "./shell.js";
import { html, render } from "./ui.js";

const root = document.getElementById("app");

function start() {
  startSession().then(
    (session) => render(html`<${Shell} session=${session} />`, root),
    (error) => {
      if (!error.problem) throw error;
      render(html`<${SessionScreen} problem=${error.problem} />`, root);
    },
  );
}

onSessionLost((problem) => render(html`<${SessionScreen} problem=${problem} lost />`, root));
window.addEventListener("hashchange", () => {
  if (new URLSearchParams(location.hash.slice(1)).has("token")) start();
});
start();
