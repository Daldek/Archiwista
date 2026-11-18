/**
 * The page's entry module: loads `main.js` with every module it imports, and
 * loads the page once more when one of them could not be fetched.
 *
 * The interface is about forty ES modules without a build (A-ADR-028), most
 * of them waiting at first for one of the six connections a browser opens to
 * a server. Chromium cancels the requests still waiting when the computer's
 * network changes (`net::ERR_NETWORK_CHANGED`: a VPN, another Wi-Fi network,
 * a container started on the computer); one module missing fails the whole
 * of `main.js`, and a module that failed stays failed in the page. So the
 * page is loaded once more; when that load fails too, the template
 * `#boot-failed` of `index.html` takes the place of the spinner: what
 * happened and a button loading the page again, never a loop of loads. This
 * module imports nothing, and its texts stand in `index.html`, as the page's
 * other texts from before the interface starts.
 */

/** `sessionStorage` key: the page was loaded once more after a failed start. */
const RELOADED = "archiwista_reloaded";

import("./main.js").then(
  () => sessionStorage.removeItem(RELOADED),
  () => {
    if (sessionStorage.getItem(RELOADED) === null) {
      sessionStorage.setItem(RELOADED, "1");
      location.reload();
      return;
    }
    const failed = document.getElementById("boot-failed").content.cloneNode(true);
    failed.querySelector("button").addEventListener("click", () => location.reload());
    document.getElementById("app").replaceChildren(failed);
  },
);
