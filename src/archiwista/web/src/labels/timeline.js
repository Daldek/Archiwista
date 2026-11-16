/**
 * Texts of the catalog's timeline (views/catalog-timeline.js; docs/SPEC.md
 * 6.5 b in its local version): its heading, grid, bars and what it needs
 * first. Layer titles and coverage labels come from the server's dictionary.
 */

export const timeline = {
  heading: "Oś czasu · {product}",
  area: "obszar „{name}”",
  whole_store: "cały magazyn — bez obszaru",
  grid: "Oś czasu: warianty w wierszach, lata w kolumnach",
  variant: "Wariant",
  year_empty: "{year}: brak danych w magazynie",
  no_data: "brak danych",
  no_campaign: "bez kampanii",
  bar_coverage: "Słupek: pokrycie lokalne obszaru (udział jego powierzchni w układzie płaskim).",
  bar_versions: "Słupek: liczba wersji w magazynie (bez obszaru; zaznacz obszar, aby zobaczyć pokrycie).",
  empty_years: "Kropka: rok bez danych.",
  keys: "Strzałki: komórki z danymi · Home, End: początek i koniec wiersza · Enter albo Spacja: wybór",
  need_product: "Wybierz produkt w panelu „Filtry”, aby zobaczyć oś czasu jego lat.",
  no_store: "Żaden magazyn nie ma plików tego produktu.",
  loading: "Wczytywanie warstw produktu…",
  empty: "Magazyn nie ma warstw tego produktu.",
  filters_note:
    "Oś czasu pokazuje warstwy produktu w magazynie (z obszarem: w obszarze); rok, jednostka, stan i wyszukiwanie zawężają tylko listę plików.",
  group_label: "Warstwy według",
  group: {
    year: "lat",
    campaign: "kampanii",
  },
};
