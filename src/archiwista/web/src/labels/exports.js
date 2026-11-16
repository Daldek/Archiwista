/**
 * Texts of a project's exports on its card (views/project-exports.js;
 * A-ADR-049, docs/SPEC.md 8.4): „Eksportuj…” with the export's name, its
 * sets (groups) and „Utwórz też plik ZIP”, the export just written with what
 * it left out, and the list of the project's exports with „Pobierz ZIP” and
 * the note that the project changed after one.
 */

export const exports = {
  title: "Eksport",
  intro:
    "Eksport kopiuje dane zestawów do folderu eksport/<nazwa>/ projektu: do podfolderów " +
    "NMT, BDOT, ORTO… w ich oryginalnych formatach, z opisem plików w README.txt.",
  open: "Eksportuj…",
  open_title:
    "Skopiuj dane przypiętych wersji do eksport/<nazwa>/ projektu: foldery NMT, BDOT, " +
    "ORTO… i README.txt",
  why_write: "Eksport zapisuje tylko właściciel projektu albo administrator.",
  form_title: "Nowy eksport",
  name: "Nazwa",
  name_hint:
    "Od 1 do 64 liter, cyfr, „.”, „_” i „-”, nie od „.”; " +
    "eksport o tej nazwie zostanie zapisany od nowa.",
  groups: "Zestawy",
  groups_hint:
    "Dane zaznaczonych zestawów, w kolejności z pliku projektu; " +
    "wersja przypięta w dwóch zestawach trafia do eksportu raz.",
  no_groups: "Projekt nie ma zestawów: eksport będzie pusty.",
  zip: "Utwórz też plik ZIP",
  zip_hint: "Ta sama zawartość w jednym pliku eksport/<nazwa>.zip, do przesłania dalej.",
  submit: "Zapisz eksport",
  cancel: "Anuluj",
  written: "Zapisano eksport „{name}”: wersje {pins}.",
  skipped_no_store: "Pominięte bez magazynu z ustawień: {count}.",
  skipped_missing: "Pominięte brakujące wersje: {count}.",
  empty: "Projekt nie ma eksportów.",
  list: "Eksporty projektu",
  written_at: "zapisany {at}",
  changed: "projekt zmieniony po eksporcie — wygeneruj ponownie",
  again: "Wygeneruj ponownie…",
  again_title: "Otwórz formularz z nazwą tego eksportu",
  copy_path: "Kopiuj ścieżkę eksportu",
  download_zip: "Pobierz ZIP",
  download_zip_title: "Pobierz plik {name}.zip z całym eksportem",
};
