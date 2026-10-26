# ADR-043: Downloads in the background: the plan window lets go, the top bar follows

**Date:** 2026-10-26
**Status:** proposed (done on the topic branch `feature/kartograf-data-output` at the author's request, part of step A12 of the plan `docs/plans/2026-10-25-archiwista-next.md`, whose approval is delegated; accepted when the author approves and merges the branch)

**Context:** The plan window of a download (ADR-042, `views/plan.js`) was a modal dialog that could not be closed while its runs went on, and it lived inside the map's step "U źródła": the author could not use the map during a download, and a change of the view lost the window and the follow-up of its runs. The jobs run in the server whatever the browser does (ADR-037, ADR-038): `GET /jobs` lists them with the session's label, `GET /jobs/{job}/events` replays and follows their events, `POST /jobs/{job}/cancel` stops one. The author asked for downloads in the background: the window closed or minimised at any time without cancelling anything, the map and the other views usable, an unobtrusive indicator of the running downloads that survives a change of the view and a reload, a list with each download's progress, its files, its cancel and a way back to its window, a toast at each end, and the map read again after a download as before. Since the browser opens at most six connections to the server, the event streams of many downloads at once could take the map's requests.

**Options:**
- Where the window lives:
  - A) In the view that opened it, as before. Rejected: a change of the view closes the window, and its runs are followed by nobody.
  - B) Over the shell: the views ask the shell to open it (`openPlan`), it outlives them, and a hidden one keeps its plan and runs.
- What a running window is:
  - C) Modal, with the closing disabled (as before). Rejected: the map is not usable.
  - D) Modal while planning and confirming (nothing is written before "Pobierz N pozycji", SPEC 10.3), not modal once something started: a window floating in a corner, with "Zwiń" (hide; it comes back from the list) and "Zamknij" (and `Esc`), neither of which cancels.
- Who follows a download:
  - E) Each window and view its own (`useJob`). Rejected: nobody follows a download whose window closed, and a reload forgets them.
  - F) One store of the shell (`downloads.js`) for the session's downloads (`download`, `project_download`, `project_repin`: the runs that write a store over the network): those started in this tab (`track`) and the queued and running ones of the session's label that `GET /jobs` lists when the page opens or comes back into view; the windows, the list and the toasts read it.
- How it follows them:
  - G) An event stream for each. Rejected: six downloads at once (one job per line of a variant) would hold every connection the browser has for the server.
  - H) Polling `GET /jobs/{job}`. Rejected: no notices, and each download's progress a poll late.
  - I) An event stream for each running download (the server runs two network jobs at a time) and for at most two queued ones; any other queued download is looked up in `GET /jobs?state=queued` every 2 s and gets its stream when it leaves the queue. One that ended while the page was away is read once (`GET /jobs/{job}`).
- Where the downloads show:
  - J) The index banner, as its store's running job (as before). Rejected: one job per store, no project downloads, nothing to act on, and a banner that comes and goes moves the map.
  - K) A button in the top bar, "Pobieranie 2/6 · 45%", summing the downloads started together (those that ended of all, and the mean share of their units), which opens the list "Pobrania w tle". The banner leaves out the jobs the button shows.

**Decision:** B, D, F, I and K.

1. **The window** (`views/plan.js`): the shell renders it (`PlanWindows` of `downloads.js`, the module loaded on the first `openPlan`). It is modal until something starts (the download, or the task of "Dodaj jako zadanie projektu"), then it floats in the bottom right corner with its runs and the line "Pobieranie trwa w tle…", and its title says "Pobieranie". "Zwiń" hides it, "Zamknij" and `Esc` close it, and the focus goes to the button of the top bar; a new window hides the one before while a download refers to it. Each run shows its state from the store with "Anuluj pobieranie". Cancelling is never implied: closing a window or the list, a change of the view or a reload stop nothing.
2. **The store** (`downloads.js`, outside Preact, given through one context whose value never changes; each component that reads it subscribes, so an event of a download draws only what shows downloads). Each download: its job's state, last progress, notices, result or error, its name (the plan window's title; else "standin · series fetch", "Projekt „Raba”"), the downloads started while another ran share a batch. This tab's list (ids, names, states, batch, whether its end was told) is kept in `sessionStorage` under the session's label, so after a reload the names stay and an end that happened meanwhile is told once.
3. **The top bar** shows the newest batch: "Pobieranie {ended}/{all} · {percent}%" (a ring of the share) while one runs, "Pobrano {succeeded}/{all}" after (an alert icon when not all succeeded), and nothing without downloads. The list under it (`role="dialog"`; `Esc` and its close button close it and return the focus to the button, a click outside closes it too) has each download newest first with its progress, notices and files or failure (the job's summary of `views/cards.js`, shared with the window), "Anuluj pobieranie" while it runs, "Pokaż okno planu" while its window is kept and "Usuń z listy" after its end, and "Usuń zakończone z listy". A live region beside the button says the state by whole downloads and tens of percent; each job's block is a polite live region as in the views.
4. **At an end** a toast says "Pobrano: …", "Pobrano częściowo: …", "Pobieranie nie powiodło się: …", "Pobieranie przerwane: …" or "Pobieranie anulowane: …" with "Pokaż wynik" (the window, else the list at that download); it goes after 10 s unless pointed at or focused. The `useDownloadEnd` listeners are told: the map reads its outlines and layers again and the step "U źródła" its report (its badges), as the window's end did before, now also for a download started elsewhere.
5. **The Projects card** hands its download and repin to the store too, so they show in the top bar after the card closes.

**Consequences:**
- The map and every view are usable during a download; only planning and the confirmation hold the page, as before.
- A download is followed by the page as long as the session lasts, whatever view is open; a download started in another tab of the session shows when this tab comes back into view or reloads.
- At most four event streams of downloads are open (two running, two queued), whatever the number of downloads.
- The Projects card follows its own job as before, so a project's download started there has two streams while the card is open.
- A view that only starts downloads or listens to their ends is not drawn again by their events. A provider drawing itself again around the shell's children was rejected: besides drawing every view for each event, Preact then counts `useId` anew for what mounts below it, and the plan window's label met an id of the map's panel.
- The rest of A12 is open: the retry, the log, the units changing colour on the map while a download runs, and the jobs of other kinds in the list.
