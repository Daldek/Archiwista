/**
 * Texts of „Zadania” (views/jobs.js; docs/SPEC.md 6.5 f, 5.6; ADR-047): the
 * queue and history of everyone's background jobs, who runs each, its
 * progress, and what can be done with it. States and kinds of a job are the
 * shared words of `common` (`job_state`, `job_kind`).
 */

export const jobs = {
  title: "Zadania w tle",
  filters_label: "Które zadania",
  filters: {
    all: "Wszystkie",
    active: "Trwa",
    errors: "Błędy",
    mine: "Moje",
  },
  filter_titles: {
    all: "Każde zadanie kolejki i historii",
    active: "Zadania, które trwają albo czekają w kolejce",
    errors: "Zadania zakończone błędem, częściowo albo przerwane",
    mine: "Zadania uruchomione przez ciebie (także przez twoich agentów)",
  },
  empty: {
    all: "Nie ma jeszcze żadnych zadań.",
    active: "Nic nie trwa ani nie czeka w kolejce.",
    errors: "Żadne zadanie nie zakończyło się błędem.",
    mine: "Nie masz żadnych zadań.",
  },
  list: "Lista zadań",
  more: "Pokaż starsze",
  oldest:
    "Widać {count} najnowszych zadań; starsze wypisuje „archiwista jobs list --cursor …” albo GET /api/v1/jobs.",
  /** Who started a job: the session's own person, an agent of a person, the scheduler. */
  who: {
    you: "Ty",
    agent: "{actor} (agent)",
    you_agent: "Ty (agent)",
    scheduler: "harmonogram",
  },
  who_label: "Uruchomił(a): {who}",
  /** A job of a project the session does not see: its kind, who and progress only. */
  hidden: "bez dostępu",
  hidden_title:
    "Zadanie danych projektu, którego nie widzisz: widać tylko rodzaj, kto je uruchomił i postęp.",
  progress: "{current} z {total}",
  time: {
    queued: "w kolejce od {time}",
    running: "od {time}",
    ended: "{time}",
  },
  subject: {
    store: "magazyn „{store}”",
    full_scan: "pełny",
    project: "projekt „{project}”",
    every_project: "wszystkie projekty",
    calls: "{producer} · {command}",
    calls_many: "{producer} · {command} · {count} {lines}",
    lines: ["polecenie", "polecenia", "poleceń"],
    refs: "{count} {objects}",
    objects: ["obiekt", "obiekty", "obiektów"],
    availability: "{producer} · {product}",
  },
  actions: {
    label: "Działania zadania",
    cancel: "Anuluj",
    cancel_title: "Zatrzymaj to zadanie; to, co już zrobione, zostaje.",
    cancelling: "Anulowanie…",
    cancel_not_yours: "Anulować zadanie może osoba, która je uruchomiła, i administrator.",
    retry: "Ponów",
    retry_title: "Uruchom to zadanie jeszcze raz jako twoje, z tymi samymi parametrami.",
    retry_no_store_write:
      "Ponowienie zapisuje magazyn, a ta sesja nie ma uprawnienia „zapis do magazynu” (rola store_writer).",
    retry_admin_only:
      "Skan magazynu, obrysy jednostek, potwierdzenie dowiązania i skan danych wszystkich projektów zleca i ponawia administrator (rola admin).",
    retried: "Ponowiono jako zadanie {job}.",
    details: "Szczegóły",
    details_hide: "Ukryj szczegóły",
    log: "Dziennik",
    log_hide: "Ukryj dziennik",
  },
  log: {
    label: "Dziennik zadania {job}",
    truncated: "Pokazano ostatni 1 MiB z {size}.",
    empty: "Dziennik jest pusty.",
  },
};
