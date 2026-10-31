/**
 * Texts of a project's jobs on its card (views/project-jobs.js, docs/SPEC.md
 * 6.5 g; A-ADR-049 decisions 11 and 12): „Weryfikuj” and „Sprawdź
 * aktualizacje” of the project, „Sprawdź aktualizacje”, „Przepnij” and
 * „Przywróć brakujące” of each group, the reasons that disable them, the
 * state of a pin's command and what the last job found at each pin.
 */

export const projectJobs = {
  verify: "Weryfikuj",
  verify_title:
    "Sprawdź sumy SHA-256 przypiętych plików w magazynie, bez sieci; nic nie zmienia",
  check: "Sprawdź aktualizacje",
  check_title: "Porównaj przypięte wersje ze źródłem (sieć); nic nie zmienia",
  check_some_title:
    "Porównaj ze źródłem przypięte wersje grup, które można sprawdzić: {groups}",
  repin: "Przepnij",
  restore: "Przywróć brakujące",
  group_actions: "Działania grupy {group}",
  group_check_label: "Sprawdź aktualizacje grupy {group}",
  group_check_title: "Porównaj przypięte wersje grupy ze źródłem (sieć); nic nie zmienia",
  repin_label: "Przepnij grupę {group}",
  repin_title:
    "Pobierz nowsze wersje grupy i przypnij je, gdy całe pobranie się uda; " +
    "inaczej przypięcia zostają",
  restore_label: "Przywróć brakujące wersje grupy {group}",
  restore_title:
    "Pobierz ponownie wersje grupy, których nie ma w magazynie; plik projektu się nie zmienia",
  /** Why a job cannot start now, in the order the card checks them (ADR-042 decision 4). */
  why: {
    write:
      "Zmienia, udostępnia, przepina i przywraca projekt jego właściciel albo administrator.",
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
      "sprawdzanie i przywracanie, a ich grupy przepięcie, są niedostępne.",
    offline: "Tryb offline: sprawdzanie, przepinanie i przywracanie potrzebują sieci.",
    running: "Trwa zadanie projektu; następne można zacząć po jego końcu.",
    no_groups: "Projekt nie ma grup przypiętych wersji.",
    no_missing: "Grupa nie ma brakujących wersji.",
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
    added: "Nowe pozycje u źródła, których grupy nie przypinają: {count}.",
    nothing_missing: "Żadna wybrana grupa nie ma brakujących wersji.",
    repin_replaced: "Grupa „{group}” przepięta: bez zmian {kept}, nowe {new}, odpięte {dropped}.",
    repin_unchanged: "Grupa „{group}”: przypięte wersje są najnowsze, nic się nie zmieniło.",
    repin_not_written:
      "Nie całe pobranie się udało, więc przypięcia grupy „{group}” zostały bez zmian " +
      "(pobrane pliki są w magazynie).",
    seconds: "Czas: {seconds} s.",
  },
};
