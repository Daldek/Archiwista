/**
 * Texts of „Zgłoś uwagę” (feedback.js: the top bar's button and its window,
 * Hydrograf's texts) and of „Zgłoszenia” (views/feedback.js: the reports for
 * administrators).
 */

export const feedback = {
  button: "Zgłoś uwagę",
  button_title: "Zgłoś uwagę: błąd albo pomysł trafi do administratora Archiwisty",
  dialog: {
    title: "Zgłoś uwagę",
    intro: "Opisz błąd lub pomysł. Zgłoszenie trafi do administratora Archiwisty.",
    message: "Opis problemu lub sugestii",
    placeholder: "Opisz co się stało lub co można poprawić…",
    counter: "{count}/{max}",
    contact: "Imię lub e-mail",
    optional: "(opcjonalnie)",
    diagnostics:
      "Dołącz dane diagnostyczne (ostatnie akcje w aplikacji, błędy, parametry zapytań)",
    preview: "Pokaż co zostanie wysłane",
    cancel: "Anuluj",
    send: "Wyślij",
    sent: "Dziękujemy! Zgłoszenie zostało zapisane.",
    empty: "Opis nie może być pusty.",
  },
  admin: {
    title: "Zgłoszenia",
    intro:
      "Uwagi wysłane przyciskiem „Zgłoś uwagę”, od najnowszej. " +
      "Otwarcie zgłoszenia oznacza je jako przeczytane.",
    unread: "nowe: {count}",
    loading: "Ładowanie zgłoszeń…",
    empty: "Brak zgłoszeń.",
    table_label: "Zgłoszenia",
    columns: { at: "Wysłano", who: "Kto", message: "Zgłoszenie", actions: "Działania" },
    new: "nowe",
    open: "Szczegóły zgłoszenia #{id}",
    mark_read: "Oznacz przeczytane",
    mark_unread: "Oznacz nieprzeczytane",
    remove: "Usuń",
    remove_label: "Usuń zgłoszenie #{id}",
    remove_confirm: "Usunąć zgłoszenie #{id}?",
    remove_yes: "Usuń",
    cancel: "Anuluj",
    local_owner: "właściciel instalacji",
    range: "zgłoszenia {first}–{last} z {total}",
    older: "Dalej",
    older_title: "Starsze zgłoszenia",
    newer: "Wstecz",
    newer_title: "Nowsze zgłoszenia",
    details: {
      contact: "Kontakt",
      account: "Konto",
      page: "Adres strony",
      browser: "Przeglądarka",
      none: "–",
      view: "Widok",
      env: "Środowisko",
      events: "Zdarzenia",
      no_events: "Brak dziennika zdarzeń.",
      no_diagnostics: "Bez danych diagnostycznych.",
    },
    event_types: { api_call: "wywołanie API", js_error: "błąd skryptu" },
  },
};
