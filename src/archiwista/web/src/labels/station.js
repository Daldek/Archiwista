/**
 * Texts of the station card (views/station.js, docs/SPEC.md 6.7 and sketch
 * 6.5 k; plan I8.5): the header with the station's type, river and the
 * year-type switch, the location or the reason without one, the coverage of
 * each variable, the tabs, the series versions, the actions and the
 * provider's formula.
 */

export const station = {
  eyebrow: "Karta stacji",
  close: "Zamknij kartę stacji",
  bad_address: "Adres karty stacji „{value}” nie wskazuje magazynu, dostawcy i kodu stacji.",
  unnamed: "(bez nazwy)",
  river: "{river} (kod hydrograficzny {code})",
  active: "czynna",
  historical: "historyczna",
  year_type: "Lata",
  year_types: { hydrological: "hydrologiczne", calendar: "kalendarzowe" },
  year_type_hint:
    "Rok hydrologiczny trwa od 1 XI do 31 X. Wybór trafia do adresu i jest zapamiętywany " +
    "dla danych {family}.",
  year_type_local: "Wybór trafia do adresu; zapamiętać go może tylko administrator.",
  year_type_failed: "Nie udało się zapamiętać wyboru lat.",
  families: { hydro: "hydrologicznych", meteo: "meteorologicznych" },
  location: {
    point: "Położenie: {lat}° N, {lon}° E",
    source: "źródło: {source}",
    catalog: "katalog {date}",
    uncertainty: "niepewność ±{metres} m",
    on_boundary: "na granicy obszaru",
    none: "Bez położenia: {reason}",
    none_note: "Stacji nie ma na mapie: Archiwista nie zgaduje położenia.",
  },
  station_page: "Strona stacji IMGW",
  station_page_title: "Strona stacji w serwisie hydro.imgw.pl (otwiera się w nowej karcie)",
  actions: {
    label: "Działania",
    show_on_map: "Pokaż na mapie",
    show_on_map_title: "Mapa produktu stacji, przybliżona na tę stację",
    copy_path: "Kopiuj ścieżkę pliku",
  },
  coverage: {
    title: "Pokrycie — osobno dla każdej zmiennej",
    none: "Stacja nie ma szeregów w indeksie.",
    series: "{dataset} · lata {year_type} {years}",
    full_years: ["pełny rok", "pełne lata", "pełnych lat"],
    longest_gap: "najdł. przerwa {from}–{to} ({units})",
    longest_gap_units: "najdł. przerwa: {units}",
    variable_title: "{variable} ({unit}): {label}",
  },
  units: {
    day: ["dzień", "dni", "dni"],
    month: ["miesiąc", "miesiące", "miesięcy"],
    half_year: ["półrocze", "półrocza", "półroczy"],
  },
  tabs: {
    label: "Widoki karty stacji",
    meta: "Metadane",
    origin: "Pochodzenie",
    tech: "Szczegóły techniczne",
  },
  meta: {
    code: "Kod",
    provider: "Dostawca",
    type: "Rodzaj",
    river: "Rzeka",
    hydrographic_code: "Kod hydrograficzny",
    river_order: "Kolejność na rzece",
    established: "Rok założenia",
    gauge_zero: "Zero wodowskazu",
    river_km: "Kilometr rzeki",
    elevation: "Wysokość",
    state: "Stan",
    catalog: "Katalog stacji",
    metres: "{value} m n.p.m.",
    kilometres: "{value} km",
  },
  origin: {
    series: "Szereg: {dataset}",
    version: "Wersja szeregów",
    file: "Plik stacji",
    sha256: "SHA-256",
    index: "Spis szeregów",
    license: "Licencja",
    catalog: "Katalog stacji",
    catalog_version: "Wersja {label}",
    location_source: "Źródło położenia",
    no_series: "Stacja nie ma szeregów w indeksie: żadnego pliku stacji.",
  },
  tech: {
    api: "Odpowiedź API karty",
    copy_json: "Kopiuj JSON",
  },
  attribution: {
    title: "Licencja i atrybucja",
    license: "Licencja {license}",
    copy: "Kopiuj atrybucję",
    none: "Szeregi stacji nie podają licencji ani formuły.",
  },
};
