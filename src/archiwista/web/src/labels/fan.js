/**
 * Texts of the Wachlarz (fan/fan.js; docs/SPEC.md 5.4, 6.5 c): its heading,
 * legend, what it needs first and the note of the large view. Layer titles
 * („2023”, „wydanie 12”), coverage labels („lokalnie 83% obszaru”) and the
 * words describing a layer (labels/set-details.js) come from elsewhere.
 */

export const fan = {
  label: "Wachlarz",
  heading: "Wachlarz lat",
  heading_note: "najnowsza warstwa na górze · każda w całości, wybrana powiększona",
  layers: ["warstwa", "warstwy", "warstw"],
  list: "Warstwy Wachlarza",
  group_label: "Warstwy według",
  group: {
    year: "lat",
    campaign: "kampanii",
  },
  legend: {
    ready: "arkusz z podglądem",
    missing: "arkusz bez gotowego podglądu",
  },
  need: {
    area: "Zaznacz obszar w panelu „Wybór”, aby zobaczyć Wachlarz jego warstw.",
    product: "Wybierz produkt w panelu „Wybór”, aby zobaczyć Wachlarz jego warstw.",
  },
  open_panel: "Otwórz panel „Wybór”",
  loading: "Wczytywanie warstw obszaru…",
  empty: "Magazyn nie ma w tym obszarze warstw tego produktu.",
  no_frame: "Obszar leży poza układami płaskimi PL i CZ: warstwy bez miniatur.",
  no_thumbnail: "bez miniatury",
  preview_ready: "Miniatura z podglądów plików w magazynie: {ready} z {total}.",
  keys: "Strzałki: następna warstwa · Enter albo Spacja: wybór",
};
