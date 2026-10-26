/**
 * Texts of a project's sharing screen (views/sharing.js, docs/SPEC.md 6.5 r,
 * A-ADR-029 erratum 2): its owner and „Przekaż…”, who sees the project with
 * the people and groups chosen, and the project's data folder.
 */

export const sharing = {
  title: "Udostępnianie · projekt {name}",
  loading: "Wczytywanie udostępnienia…",
  owner: "właściciel: {name}",
  no_owner: "bez właściciela: projektem zarządzają administratorzy",
  transfer: "Przekaż…",
  transfer_label: "Nowy właściciel",
  transfer_pick: "wybierz osobę",
  transfer_hint: "Po zapisaniu projektem zarządzają nowy właściciel i administratorzy.",
  visibility: "Kto widzi projekt (administratorzy widzą każdy):",
  visibilities: {
    public: "wszyscy",
    users: "wybrane osoby",
    group: "wybrane grupy",
    private: "tylko właściciel",
  },
  add_person: "+ osoba",
  add_group: "+ grupa",
  remove: "Usuń: {name}",
  person: "{name} ({id})",
  folder: "Folder danych własnych",
  folder_hint:
    "Domyślnie <katalog projektu>/dane (puste pole go przywraca); leży w katalogu projektu — " +
    "administrator może wskazać inny, poza magazynami i folderami innych projektów. " +
    "Migawki trafią do jego .wersje/.",
  cancel: "Anuluj",
  save: "Zapisz",
};
