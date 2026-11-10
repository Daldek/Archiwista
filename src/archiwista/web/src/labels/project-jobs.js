/**
 * Texts of a project's jobs on its card (views/project-jobs.js, docs/SPEC.md
 * 6.5 g; A-ADR-049 decisions 11 and 12): „Weryfikuj” and „Sprawdź
 * aktualizacje” of the project, „Sprawdź aktualizacje”, „Przepnij” and
 * „Przywróć brakujące” of each set (a group), the reasons that disable them
 * and „Zamknij zestaw”, the state of a pin's command, what the last job
 * found at each pin, and the plan window of a set's re-pin and restore
 * (views/project-plan.js; ADR-042 erratum 2).
 */

export const projectJobs = {
  verify: "Weryfikuj",
  verify_title:
    "Sprawdź sumy SHA-256 przypiętych plików w magazynie, bez sieci; nic nie zmienia",
  check: "Sprawdź aktualizacje",
  check_title: "Porównaj przypięte wersje ze źródłem (sieć); nic nie zmienia",
  check_some_title:
    "Porównaj ze źródłem przypięte wersje zestawów, które można sprawdzić: {groups}",
  repin: "Przepnij",
  restore: "Przywróć brakujące",
  group_actions: "Działania zestawu {group}",
  group_check_label: "Sprawdź aktualizacje zestawu {group}",
  group_check_title: "Porównaj przypięte wersje zestawu ze źródłem (sieć); nic nie zmienia",
  repin_label: "Przepnij zestaw {group}",
  repin_title:
    "Pobierz nowsze wersje zestawu i przypnij je, gdy całe pobranie się uda; " +
    "inaczej przypięcia zostają",
  restore_label: "Przywróć brakujące wersje zestawu {group}",
  restore_title:
    "Pobierz ponownie wersje zestawu, których nie ma w magazynie; plik projektu się nie zmienia",
  /** Why a job cannot start now, in the order the card checks them (ADR-042 decision 4). */
  why: {
    write:
      "Zmienia, udostępnia, usuwa, przepina i przywraca projekt jego właściciel albo administrator.",
    unknown_store:
      "Magazyn projektu dla „{producer}” nie pasuje do żadnego magazynu z ustawień: " +
      "wskaż go w „Zmień…”.",
    store_write:
      "Przepięcie i przywracanie zapisują magazyn, a ta sesja nie ma uprawnienia " +
      "„zapis do magazynu” (rola store_writer).",
    no_commands:
      "Producent „{producer}” nie udostępnia jeszcze poleceń: jego wersji nie można " +
      "sprawdzić, przepiąć ani przywrócić.",
    command_not_rebuildable:
      "Producent nie odtworzy polecenia niektórych wersji (powód przy wersji): ich " +
      "sprawdzanie i przywracanie, a ich zestawów przepięcie, są niedostępne.",
    offline: "Tryb offline: sprawdzanie, przepinanie i przywracanie potrzebują sieci.",
    set_closed: "Zestaw jest zamknięty: otwórz go do edycji, aby go przepiąć.",
    running: "Trwa zadanie projektu; następne można zacząć po jego końcu.",
    no_groups: "Projekt nie ma zestawów przypiętych wersji.",
    no_missing: "Zestaw nie ma brakujących wersji.",
    /** Why „Zamknij zestaw” cannot close a set now. */
    set_job_active: "Zadanie „{kind}” zapisuje do zestawu.",
    set_pins_not_ok: [
      "{count} przypięcie nie jest w stanie ok: " +
        "brak {missing}, inna suma {mismatch}, nieznany magazyn {unknown}.",
      "{count} przypięcia nie są w stanie ok: " +
        "brak {missing}, inna suma {mismatch}, nieznany magazyn {unknown}.",
      "{count} przypięć nie jest w stanie ok: " +
        "brak {missing}, inna suma {mismatch}, nieznany magazyn {unknown}.",
    ],
    set_empty: "Zestaw jest pusty.",
  },
  reasons: "Dlaczego część działań jest wyłączona",
  /** The state of a pin's command (A-ADR-049 decision 12). */
  command: {
    not_rebuildable: "bez polecenia",
    not_rebuildable_title:
      "Producent nie odtworzy polecenia tej wersji: nie da się jej sprawdzić ani przywrócić",
  },
  /** What the last job found at a pin, by the job's kind. */
  mark: {
    project_verify: {
      ok: "nienaruszona",
      corrupt: "inna treść w magazynie",
      missing: "brak w magazynie",
      content_match: "ta sama treść w innej wersji",
      no_store: "magazyn nieznany",
    },
    project_check: {
      current: "aktualna",
      newer: "jest nowsza",
      missing: "brak w magazynie",
      removed: "polecenie już jej nie wybiera",
      unverifiable: "źródło nie mówi",
      check_failed: "sprawdzenie nieudane",
      not_checkable: "bez sprawdzenia",
    },
    project_restore: {
      restored: "przywrócona",
      content_match: "przywrócona ta sama treść, inne bajty",
      not_restored: "nieprzywrócona",
      not_restorable: "nie do przywrócenia",
    },
  },
  newer: "nowsza: {label}",
  found: "w wersji {version}",
  not_restored: {
    other_content: "źródło dało inną treść",
    not_returned: "źródło jej nie dało",
  },
  /** The summary of a project's job (the job status under the actions). */
  done: {
    pins: "Wersje: {total} — {counts}.",
    added: "Nowe pozycje u źródła, których zestawy nie przypinają: {count}.",
    nothing_missing: "Żaden wybrany zestaw nie ma brakujących wersji.",
    repin_replaced: "Zestaw „{group}” przepięty: bez zmian {kept}, nowe {new}, odpięte {dropped}.",
    repin_unchanged: "Zestaw „{group}”: przypięte wersje są najnowsze, nic się nie zmieniło.",
    repin_not_written:
      "Nie całe pobranie się udało, więc przypięcia zestawu „{group}” zostały bez zmian " +
      "(pobrane pliki są w magazynie).",
    seconds: "Czas: {seconds} s.",
  },
  /**
   * The plan window of a set's „Przepnij” and „Przywróć brakujące”: the set's
   * check, then the plan to confirm (views/project-plan.js).
   */
  plan: {
    title: {
      repin: "Przepiąć zestaw „{group}”?",
      restore: "Przywrócić brakujące wersje zestawu „{group}”?",
    },
    checking: "Sprawdzanie zestawu u źródła…",
    checking_progress: "Sprawdzanie zestawu u źródła: {current} z {total} {commands}…",
    /** After „z”: the genitive („z 1 polecenia”, „z 2 poleceń”). */
    commands: ["polecenia", "poleceń", "poleceń"],
    /** A check that ended without its plan and without an error to tell. */
    ended: "Sprawdzenie zakończone stanem „{state}” nie dało planu.",
    pins: "Wersje zestawu: {total} — {counts}.",
    no_pins: "Zestaw nie ma przypiętych wersji.",
    changes: "Wersje, które przepięcie zmieni",
    no_changes: "Sprawdzenie nie znalazło wersji do zmiany.",
    added: "Nowe pozycje u źródła, które przepięcie przypnie",
    missing: "Brakujące wersje, które przywracanie pobierze ponownie",
    not_checked: "Wersje, których nie sprawdzono",
    /** A version's pinned label and the one the source has now. */
    change: "{pinned} → {available}",
    calls: "Polecenia producenta",
    copy_line: "polecenie producenta",
    /** How the check of each call went (`status` of `result.calls`). */
    call: {
      ok: "sprawdzone",
      partial: "sprawdzone częściowo",
      failed: "bez planu",
    },
    note: {
      repin:
        "Przepięcie przypina dopiero, gdy całe pobranie się uda; " +
        "inaczej przypięcia zostają bez zmian.",
      restore:
        "Przywracanie nie zmienia pliku projektu: pobiera do magazynu tylko brakujące wersje.",
      again:
        "Zadanie planuje jeszcze raz u źródła: pobierze to, co źródło będzie miało " +
        "w chwili pobierania.",
    },
  },
};
