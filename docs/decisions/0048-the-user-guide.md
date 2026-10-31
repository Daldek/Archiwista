# ADR-048: The user guide: a page of its own at `/instrukcja`, readable without a session

**Date:** 2026-10-31
**Status:** proposed (accepted when the author approves and merges `feature/instrukcja`)

**Context:** People new to Archiwista, and to a team server, need a short guide in the language of the interface that shows its real workflows. Hydrograf, an application of the same ecosystem, publishes such a guide as a static page of slides at `/instrukcja`, opened by „Instrukcja” in its top bar. Archiwista's interface is one page at `/` whose views are addressed by `?view=…`, with its files under `/static/…`; every `/api/*` request needs a session and the interface files need none (SPEC 10.1); every answer carries a CSP that allows only the server's own scripts and stylesheets, so no inline style or script, and no framing; a browser reads a page outside `/api/` from another site only as a top-level navigation (Fetch Metadata, `security.origin_rejection`). The top bar is the one place shared by local and team mode: the account menu exists in team mode only.

**Options:**
- Where: A) a page of its own at `/instrukcja`, its files under `/static/guide/`; B) the same page at an English path, `/guide`; C) a view of the interface, `?view=guide`; D) a document of the repository only.
- Access: E) as the interface page, without a session, under every other rule of the request; F) behind the session, as `/api/*`.

**Decision:** A and E.

1. **A page of its own (A).** `GET /instrukcja` answers `web/guide/index.html` as the interface page is answered (`InterfaceFiles`: `ETag`, `Cache-Control: no-cache`, revalidated on every use; `404 not_found` with `api.interface_missing` when the file is missing); its stylesheet and pictures are interface files under `/static/guide/`. Outside the interface's router the page needs no JavaScript and no session, so it opens before a sign-in, from a link on another page and in print, one slide a page. The path is Polish like the page and the interface, and it is Hydrograf's: one address of the guide in the ecosystem; the names in the code stay English (`GUIDE_PATH`, `web/guide/`). B would put the one English word of the guide in its address; C needs a session, the shell and JavaScript, and is neither readable before a sign-in nor printable as slides; D does not reach the people who use a running server.
2. **No session (E).** The guide holds no data, only pictures of the test stores and the labels of the interface. It goes through every rule an interface file goes through: in team mode TLS or a trusted proxy, `Host` and a present `Origin` equal to the team's origin, HSTS; in both modes `Origin` and `Sec-Fetch-Site` (a read from another site only as a top-level navigation, never in a frame), the CSP of the settings, `Referrer-Policy: no-referrer` and `nosniff`. Nothing of `security.py` changes. F would keep a person who cannot sign in from the page that tells how, and protect nothing.
3. **No inline style or script.** The page links `/static/styles.css`, whose tokens give it the interface's colours, fonts and shadows, and `/static/guide/guide.css`, and has no script. The pictures are WebP files of the package (about 325 kB together), each a link to itself at full size.
4. **The link.** „Instrukcja” in the top bar, after „Szukaj”, opens the guide in a new tab (`rel="noopener noreferrer"`), so the work in the interface stays as it is; on a phone it is its icon alone, as the search is.
5. **The pictures.** They are taken from the real interface of the branch by the interface tests and their fixtures (`ARCHIWISTA_SCREENSHOTS`), with local paths covered, and the guide says they show test stores. A change of the interface that makes a picture or a sentence of the guide untrue replaces it.

**Consequences:**
- Anyone who reaches the server reads the guide without signing in; it shows nothing the interface files do not already show (the sign-in page, the code and labels of every view).
- The guide is a document in Polish, outside the message catalogs: its texts change with the interface by hand, and the labels it names are the interface's, checked when it is written. USAGE.md stays the full description, in English.
- `/instrukcja` is a page of the application, not of the API (no OpenAPI operation). Tests: `tests/unit/test_security.py` (no session, headers, revalidation, a link from another site), `tests/contract/test_package_data.py` (its files ship in the wheel), `tests/e2e/test_guide.py` (the link, every picture, the CSP, a phone's width, a team server before and after a sign-in).
