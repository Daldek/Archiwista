/**
 * Texts of a project's exports on its card (views/project-exports.js;
 * A-ADR-049 decision 13, docs/SPEC.md 8.4): „Eksportuj…” with the export's
 * name and groups, the export just written with what it left out, and the
 * list of the project's exports with the note that the project changed after
 * one.
 */

export const exports = {
  title: "Zestawy",
  open: "Eksportuj…",
  open_title:
    "Zapisz zestaw w katalogu zestawy/ projektu: pliki.txt (przypięte wersje, np. dla " +
    "Hydrografu) i ATRYBUCJE.txt",
  why_write: "Zestaw zapisuje tylko właściciel projektu albo administrator.",
  form_title: "Nowy zestaw",
  name: "Nazwa",
  name_hint:
    "Od 1 do 64 liter, cyfr, „.”, „_” i „-”, nie od „.”; " +
    "zestaw o tej nazwie zostanie zapisany ponownie.",
  groups: "Grupy",
  groups_hint:
    "Przypięcia zaznaczonych grup, w kolejności z pliku projektu; " +
    "wersja przypięta w dwóch grupach raz.",
  no_groups: "Projekt nie ma grup: zestaw będzie pusty.",
  submit: "Zapisz zestaw",
  cancel: "Anuluj",
  written: "Zapisano zestaw „{name}”: wersje {pins}.",
  skipped_no_store: "Pominięte bez magazynu z ustawień: {count}.",
  skipped_missing: "Pominięte brakujące wersje: {count}.",
  empty: "Projekt nie ma zestawów.",
  list: "Zestawy projektu",
  written_at: "zapisany {at}",
  changed: "projekt zmieniony po eksporcie — wygeneruj ponownie",
  again: "Wygeneruj ponownie…",
  again_title: "Otwórz formularz z nazwą tego zestawu",
  copy_path: "Kopiuj ścieżkę zestawu",
};
