/**
 * Texts of the administrators' views (docs/SPEC.md 6.5 p and q, ADR-046):
 * „Konta” (views/accounts.js) — the accounts with their roles, groups and
 * passwords, a new account, a temporary password shown once, ending the
 * sessions, disabling and removing an account; „Grupy” (views/groups.js) —
 * the groups with their members, a new group, the members and the removal.
 */

import { account } from "./account.js";

export const admin = {
  roles: account.menu.roles,
  accounts: {
    title: "Konta",
    intro:
      "Konta osób tego serwera. Hasło tymczasowe nadaje serwer i pokazuje je tylko raz; nadanie go kończy sesje konta.",
    add: "Nowe konto",
    search: "Szukaj konta",
    columns: {
      id: "Konto",
      name: "Nazwa",
      roles: "Role",
      groups: "Grupy",
      password: "Hasło",
      state: "Stan",
    },
    manage: "Zarządzaj",
    manage_label: "Zarządzaj kontem {id}",
    none: "—",
    no_match: "Żadne konto nie pasuje do „{query}”.",
    loading: "Wczytywanie kont…",
    password: {
      none: "brak",
      set: "ustawione",
      temporary: "tymczasowe · do {date}",
      expired: "tymczasowe wygasło {date}",
    },
    state: { enabled: "aktywne", disabled: "wyłączone" },
  },
  account: {
    title: "Konto · {id}",
    roles: "Role",
    save_roles: "Zapisz role",
    roles_saved: "Role zapisane: działają od następnego żądania tej osoby.",
    password: "Hasło",
    temporary: "Hasło tymczasowe…",
    temporary_hint:
      "Serwer wygeneruje hasło ważne 72 godziny; osoba zmieni je przy pierwszym logowaniu, a jej sesje zakończą się teraz.",
    temporary_set: "Ustaw hasło tymczasowe",
    temporary_title: "Hasło tymczasowe · {id} (widoczne tylko teraz)",
    temporary_copy: "hasło tymczasowe konta {id}",
    temporary_until:
      "Ważne do {time}; przy pierwszym logowaniu trzeba je zmienić; sesje konta {id} zostały zakończone.",
    sessions: "Sesje",
    end_sessions: "Zakończ sesje",
    sessions_hint: "Kończy każdą sesję konta i jego agentów; osoba zaloguje się ponownie.",
    sessions_ended: "Sesje konta {id} i jego agentów zakończono.",
    state: "Stan",
    disable: "Wyłącz",
    enable: "Włącz",
    disable_hint: "Wyłączone konto nigdzie nie działa, a jego sesje kończą się od razu.",
    remove: "Usuń…",
    remove_confirm:
      "Usunąć konto {id}? Znika z grup i z udostępnień projektów; jego projekty zostają bez właściciela.",
    remove_yes: "Usuń konto",
    cancel: "Anuluj",
    close: "Zamknij",
  },
  new_account: {
    title: "Nowe konto",
    id: "Konto",
    id_hint: "Małe litery, cyfry, „.”, „_” i „-”, najwyżej 64 znaki, np. kasia.wrona.",
    name: "Nazwa",
    name_hint: "Imię i nazwisko; bez niej nazwą jest konto.",
    roles: "Role",
    submit: "Utwórz konto",
    created:
      "Konto {id} utworzone. Nadaj mu hasło tymczasowe, aby osoba mogła się zalogować.",
  },
  groups: {
    title: "Grupy",
    intro:
      "Grupy osób, np. działy. Projekt udostępniony grupie widzą jej członkowie; zmiana członków działa od następnego żądania osoby.",
    add: "Nowa grupa",
    columns: { id: "Grupa", name: "Nazwa", members: "Członkowie", actions: "Działania" },
    count: "{count}: {names}",
    more: "…",
    none: "—",
    empty: "Nie ma jeszcze żadnej grupy.",
    loading: "Wczytywanie grup…",
    members: "Członkowie…",
    members_label: "Członkowie grupy {id}",
    remove: "Usuń…",
    remove_label: "Usuń grupę {id}",
  },
  members: {
    title: "Członkowie · {id}",
    legend: "Członkowie",
    person: "{name} ({id})",
    disabled: "wyłączone",
    no_accounts: "Nie ma jeszcze żadnego konta.",
    loading: "Wczytywanie kont…",
    save: "Zapisz",
  },
  new_group: {
    title: "Nowa grupa",
    id: "Grupa",
    id_hint: "Małe litery, cyfry, „.”, „_” i „-”, najwyżej 64 znaki, np. hydro.",
    name: "Nazwa",
    name_hint: "Np. Dział hydrologii; bez niej nazwą jest identyfikator grupy.",
    submit: "Utwórz grupę",
  },
  remove_group: {
    title: "Usunąć grupę {id}?",
    text: "Jej członkowie przestaną widzieć projekty udostępnione tylko tej grupie; ich konta zostają.",
    yes: "Usuń grupę",
  },
};
