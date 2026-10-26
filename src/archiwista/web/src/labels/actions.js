/**
 * Texts of the actions at the source (map/source.js, views/plan.js; docs/SPEC.md
 * 6.3, 6.4, 6.5 h, UC-15): the step „U źródła” of the „Wybór” panel with the
 * rows of a report and their variants and the pasted command, and the „Okno
 * planu” of a download with „Dodaj jako zadanie projektu”. Coverage labels
 * („pełne · 2 kampanie”) and store badges („pobrane 5/12”) come from the
 * server's dictionary; the words of a plan and of a run's files follow it
 * (archiwista/messages/job.py), so the interface and `archiwista jobs` say the
 * same thing.
 */

export const actions = {
  source: {
    title: "U źródła",
    need_area: "Zaznacz obszar, aby sprawdzić, co ma dla niego źródło.",
    no_products: "Żaden zainstalowany producent nie sprawdza dostępności u źródła.",
    product: "Produkt u źródła",
    product_value: "{product} · {producer}",
    store: "Magazyn docelowy",
    store_value: "Magazyn docelowy: {name}",
    check: "Sprawdź u źródła",
    check_title: "Zapytaj źródło, co ma dla obszaru: przez sieć, bez zapisu w magazynie",
    recheck: "Sprawdź ponownie",
    recheck_title: "Zapytaj źródło jeszcze raz, choć raport ma mniej niż 7 dni",
    checked: "Raport z {date}",
    no_report: "Archiwista nie ma jeszcze raportu tego obszaru i produktu: sprawdź u źródła.",
    loading: "Wczytywanie raportu…",
    offline: "Brak sieci — pokazuję tylko magazyn.",
    offline_title: "Tryb offline: Archiwista nie łączy się ze źródłem",
    offline_no_report:
      "Archiwista nie ma raportu źródła dla tego obszaru i produktu, a bez sieci go nie sprawdzi. Co z obszaru jest już w magazynie, pokazuje krok „Stan lokalny”.",
    failed_part: "Nie sprawdzono części „{part}”: {detail}",
    rows: "Lata u źródła",
    no_rows: "Źródło nie ma tego produktu dla obszaru.",
    variants: ["wariant", "warianty", "wariantów"],
    more: "+{count} {word}",
    more_title: "Pokaż pozostałe warianty tego roku",
    less_title: "Ukryj pozostałe warianty tego roku",
    other: "Pozostałe warianty roku {year}",
    no_year: "bez roku",
    size_unknown: "rozmiar nieznany",
    formats: "Formaty",
    default_format: "format domyślny",
    download: "Pobierz…",
    download_title: "Okno planu: co i ile zostanie pobrane do magazynu; nic nie zapisuje się przed potwierdzeniem",
    download_offline: "Pobieranie potrzebuje sieci: tryb offline jest włączony",
    no_commands: "Producent nie podał polecenia, które pobiera ten wariant",
    paste: "Wklej polecenie producenta",
    paste_placeholder: "np. kartograf elevation download --product nmt --sheet N-34-130-D-d-2-4",
    paste_hint:
      "Polecenie jak w wierszu poleceń; Archiwista zapisze do magazynu „{store}” zamiast katalogu z -o albo --root. Najpierw pokaże plan.",
    paste_submit: "Zaplanuj…",
    paste_title: "{producer} · {command}",
    paste_no_producer: "Nie wiadomo, czyje to polecenie: zacznij je od nazwy producenta ({producers}).",
  },
  plan: {
    title: "Pobrać?",
    area: "obszar {name}",
    format: "Format",
    format_choose: "Wybierz format: żaden format tego wariantu nie jest domyślny, więc nic nie zostało wybrane za Ciebie.",
    format_no_lines: "Producent nie podał polecenia dla tego formatu",
    store: "Magazyn",
    root: "Katalog producenta",
    copy_root: "katalog producenta w magazynie",
    checking: "Sprawdzanie u źródła: {done} z {total} {commands}…",
    /** After „z”: the genitive („z 1 polecenia”, „z 2 poleceń”). */
    commands: ["polecenia", "poleceń", "poleceń"],
    positions: ["pozycja", "pozycje", "pozycji"],
    /** After „Pobierz” and „obejmie”: the accusative („1 pozycję”). */
    positions_accusative: ["pozycję", "pozycje", "pozycji"],
    todo: "Do pobrania: {count}",
    size: "rozmiar {size}",
    size_partial: "rozmiar co najmniej {size}",
    size_unknown: "rozmiar nieznany",
    size_hint: "Producent nie podał rozmiaru wszystkich pozycji do pobrania.",
    status: {
      current: "aktualne",
      newer: "nowsze u źródła",
      missing: "brak w magazynie",
      unverifiable: "nie do sprawdzenia",
      check_failed: "niesprawdzone",
    },
    entries: "Pozycje planu",
    columns: {
      path: "Plik w magazynie",
      status: "Stan",
      local: "W magazynie",
      source: "U źródła",
      size: "Rozmiar",
    },
    no_label: "brak",
    unknown: "nieznany",
    conflicts: "Producent odmówi zapisu: {count} {positions}",
    conflict: {
      nested_store: "w tym miejscu leży inny magazyn",
      not_empty: "miejsce zapisu nie jest puste",
    },
    not_checked: "Pozycje niesprawdzone u źródła: {count}. Pobranie ich nie obejmie.",
    line: "Polecenie producenta",
    copy_line: "polecenie producenta",
    notices: "Komunikaty producenta",
    failed_line: "Polecenie „{line}” nie dało planu.",
    large: "Rozumiem: pobranie obejmie {positions}, {size}.",
    nothing: "Magazyn ma już wszystko, co podało źródło: nie ma czego pobrać.",
    no_write:
      "Pobieranie zapisuje magazyn, a ta sesja nie ma uprawnienia „zapis do magazynu” (rola store_writer). Plan można obejrzeć.",
    submit: "Pobierz {count} {positions}",
    submit_unplanned: "Pobierz",
    cancel: "Anuluj",
    close: "Zamknij",
    task: "Dodaj jako zadanie projektu",
    task_project: "Projekt",
    task_project_choose: "Wybierz projekt…",
    task_name: "Nazwa zadania",
    task_name_example: "teren-2023",
    task_name_hint: "Nazwa zadania w manifeście projektu; jej zasady sprawdza producent.",
    task_added: "Dodano zadanie „{name}” do projektu",
    /** After „ma”: the accusative („1 polecenie”, „2 polecenia”, „5 poleceń”). */
    lines: ["polecenie", "polecenia", "poleceń"],
    task_lines: "Zadanie projektu to jedno polecenie, a ten format wariantu ma {count} {commands}.",
    task_loading: "Wczytywanie projektów magazynu…",
    task_no_project_list: "Nie udało się wczytać projektów magazynu.",
    task_no_project:
      "W magazynie „{store}” nie ma projektu producenta {producer}; projekt zakłada administrator w widoku Projekty.",
    task_no_write:
      "Zadania dodaje właściciel projektu albo administrator, a ta sesja nie może zmienić żadnego projektu tego producenta w tym magazynie.",
    task_no_call: "Polecenia nie udało się odczytać, więc nie można go dodać jako zadania.",
    submit_task: "Dodaj zadanie",
    submit_task_download: "Dodaj zadanie i pobierz {count} {positions}",
    files: "Pliki: {files} ({counts}); jednostki z błędem: {failed}.",
    file_status: {
      new: "nowe",
      unchanged: "bez zmian",
      relabeled: "z nową etykietą",
    },
    files_title: "Pliki w magazynie",
    failed_items: "Jednostki z błędem",
  },
};
