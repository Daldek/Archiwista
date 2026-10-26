/**
 * Texts of signing in to a team server and of the person's account
 * (views/login.js; docs/SPEC.md 6.5 n, ADR-046): the sign-in, the wait after
 * failed attempts, the company's sign-in through its proxy and the change of
 * a password.
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
  },
  show: "Pokaż",
  show_label: "Pokaż hasło",
  wait_minutes: "{minutes} min {seconds} s",
  wait_seconds: "{seconds} s",
};
