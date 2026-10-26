/**
 * Texts of signing in to a team server and of the person's account
 * (views/login.js, the account menu of shell.js; docs/SPEC.md 6.5 n and o,
 * ADR-046): the sign-in, the wait after failed attempts, the company's
 * sign-in through its proxy, the change of a password, the sessions and an
 * agent's token.
 */

export const account = {
  sign_in: {
    title: "Logowanie",
    account: "Konto",
    password: "Hasło",
    submit: "Zaloguj",
    proxy: "Zaloguj kontem firmowym",
    proxy_hint: "Firmowe logowanie rozpoznało cię na tym komputerze.",
    forgot: "Nie pamiętasz hasła? Administrator ustawi hasło tymczasowe.",
    lost: "Sesja wygasła albo została zakończona. Zaloguj się ponownie.",
    wait: "Zbyt wiele nieudanych prób: spróbuj ponownie za {wait}.",
  },
  change: {
    title: "Zmień hasło",
    title_temporary: "Zmień hasło tymczasowe",
    temporary_note:
      "Zalogowano hasłem tymczasowym: ustaw własne hasło, zanim zaczniesz pracę.",
    current: "Obecne hasło",
    new: "Nowe hasło",
    repeat: "Powtórz nowe hasło",
    rule: "Co najmniej 12 znaków, dowolnych; nie nazwa konta i nie popularne hasło.",
    mismatch: "Powtórzone hasło różni się od nowego.",
    submit: "Zmień hasło",
    sign_out: "Wyloguj",
    cancel: "Anuluj",
    ended: "Zmiana hasła kończy pozostałe sesje tego konta i jego agentów.",
    done: "Hasło zostało zmienione; pozostałe sesje tego konta i jego agentów zakończono.",
  },
  menu: {
    open: "Konto: {name}",
    roles: { admin: "administrator", store_writer: "zapis do magazynu" },
    no_roles: "bez ról",
    groups: "grupy: {groups}",
    agent: "sesja agenta",
    change_password: "Zmień hasło…",
    sessions: "Sesje…",
    sessions_count: "Sesje ({count})…",
    token: "Token dla agenta…",
    sign_out: "Wyloguj",
  },
  sessions: {
    title: "Sesje · {account}",
    loading: "Wczytywanie sesji…",
    current: "ta sesja",
    browser: "przeglądarka",
    agent: "agent (token)",
    since: "od {time}",
    until: "do {time}",
    end: "Zakończ",
    end_label: "Zakończ sesję {label}",
    end_others: "Zakończ pozostałe sesje",
    close: "Zamknij",
  },
  token: {
    title: "Token dla agenta",
    intro:
      "Jednorazowy adres sesji agenta (np. skryptu albo asystenta AI), który działa w imieniu konta {account} z jego rolami. Adres jest ważny 5 minut i działa tylko raz.",
    issue: "Wystaw adres",
    address: "adres sesji agenta",
    shown_once: "Adres jest widoczny tylko teraz; ważny do {time}. Sesja agenta: {label}.",
    close: "Zamknij",
  },
  show: "Pokaż",
  show_label: "Pokaż hasło",
  wait_minutes: "{minutes} min {seconds} s",
  wait_seconds: "{seconds} s",
};
