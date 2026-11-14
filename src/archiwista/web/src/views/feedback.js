/**
 * „Zgłoszenia” (docs/SPEC.md 6.5 and 9.2; administrators): the reports people
 * sent with „Zgłoś uwagę” (feedback.js), shown by Nogat's kit view
 * `<nogat-admin-feedback>` (nogat/nogat-admin.js, DEV-15.13) alone in this
 * view: 50 a page, newest first, the unread count, „Tylko nieprzeczytane”,
 * marking read and unread, „Usuń” after a confirmation, and each report's
 * `context` (the account, the contact, the page, the browser and the attached
 * diagnostics) folded under „Kontekst”, every text a text node. Archiwista
 * keeps its own sign-in (`auth="session"`): the view's requests go through
 * `adminFetch` of api.js with the session's CSRF header, and a lost session
 * goes to the shell like any other. Anyone but an administrator gets the
 * server's refusal.
 */

import "../../nogat/nogat-admin.js";
import { adminFetch, API_PREFIX } from "../api.js";
import { html, loadStylesheet } from "../ui.js";

await Promise.all([
  loadStylesheet(new URL("../../nogat/nogat-admin.css", import.meta.url)),
  loadStylesheet(new URL("./admin.css", import.meta.url)),
]);

/** The core feedback route of DEV-15.13 under Archiwista's API prefix. */
const ENDPOINT = `${API_PREFIX}/admin/feedback`;

/** Give the kit's view Archiwista's requests before its first one. */
function attach(element) {
  if (element) element.adminFetch = adminFetch;
}

/** The view „Zgłoszenia” (route `feedback`). */
export default function FeedbackView() {
  return html`<div class="page admin-page">
    <nogat-admin-feedback endpoint=${ENDPOINT} auth="session" ref=${attach}></nogat-admin-feedback>
  </div>`;
}
