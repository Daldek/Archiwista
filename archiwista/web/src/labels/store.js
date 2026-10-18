/**
 * Texts of the Store view (views/store.js, docs/SPEC.md UC-07 and UC-13):
 * the state of a store, its source and the index, disk usage per product
 * with each version counted once, the report of versions neither current
 * nor pinned, problems with their fixes and the store's background jobs.
 */

export const store = {
  title: "Magazyn",
  stores_label: "Magazyny",
  no_store: "Nie skonfigurowano jeszcze żadnego magazynu.",
  unknown: "Nie ma magazynu „{store}” w ustawieniach.",
  settings: "Ustawienia",
  status_line: {
    available: "dostępny",
    unavailable: "niedostępny",
    unknown: "jeszcze nie zeskanowany",
  },
  unavailable_since: "Niedostępny od {at}",
  actions: {
    refresh: "Odśwież",
    refresh_hint: "Skan przyrostowy: czyta tylko zmienione segmenty i nowe wersje.",
    footprints: "Uzupełnij obrysy jednostek",
    footprints_hint: "Pobiera z sieci granice jednostek (TERYT, KU) dla wersji bez obrysu.",
    footprints_offline:
      "Niedostępne w trybie offline: obrysy jednostek pobiera się z sieci. Wyłącz tryb offline w Ustawieniach, aby je uzupełnić.",
  },
  state: {
    title: "Stan",
    indexed_at: "Ostatnie pełne przejście",
    never: "jeszcze nie",
    counts: "Zawartość indeksu",
    counts_value: "{slots} {slots_word} · {versions} {versions_word}",
    missing_versions: "brak w magazynie: {count}",
    unlocated_versions: "bez położenia: {count}",
    issues: "problemy: {count}",
    last_scan: "Ostatni skan",
    last_scan_none: "jeszcze nie było",
    last_scan_value: "{at} · {state}",
    duration: "{seconds} s",
    source: "Źródło danych",
    source_value: "{producer} {version}",
    index: "Indeks lokalny",
    index_value: "schemat {schema} · {size} · utworzony {created}",
    actor: "Wykonawca",
  },
  slots: ["plik", "pliki", "plików"],
  usage: {
    title: "Zajętość według produktów",
    hint: "Każda wersja liczona raz: dowiązania (ścieżka standardowa, full_sheet/) i ta sama treść pod inną etykietą nic nie dodają.",
    product: "Produkt",
    versions: "Wersje",
    bytes: "Zajętość",
    unused_versions: "Niebieżące i nieprzypięte",
    unused_bytes: "Ich zajętość",
    total: "Razem",
    unknown_product: "Nierozpoznane segmenty (nieznany produkt)",
    list_title: "Niebieżące i nieprzypięte wersje produktu „{product}” w Katalogu",
    empty: "Indeks nie ma jeszcze wersji z tego magazynu.",
  },
  unused: {
    title: "Niebieżące i nieprzypięte",
    summary:
      "{versions} {versions_word} ani bieżących, ani w full_sheet/, ani przypiętych w widocznych projektach: {bytes}. Po ich usunięciu zwolni się {reclaimable} (treści, których nie ma żadna inna wersja).",
    none: "Każda wersja jest bieżąca, w full_sheet/ albo przypięta w projekcie.",
    note: "Archiwista niczego nie usuwa — raport służy decyzji; usuwa się ręcznie albo poleceniami producenta.",
    catalog: "Pokaż w Katalogu",
  },
  problems: {
    title: "Problemy magazynu",
  },
  projects: {
    title: "Projekty korzystające z magazynu",
    none: "Żaden widoczny projekt nie wskazuje tego magazynu.",
    missing: "brakujące przypięcia: {count}",
    invalid: "błędny manifest",
  },
};
