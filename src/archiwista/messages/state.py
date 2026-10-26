"""The state database: accounts, groups, sharing and backup."""

from archiwista.messages import Text

MESSAGES = {
    "newer": Text(
        (
            "The state database {path} comes from a newer version of Archiwista"
            " (schema {version}, this version supports {supported}); install a newer"
            " version of Archiwista. The database remains unchanged."
        ),
        (
            "Baza stanu {path} pochodzi z nowszej wersji Archiwisty (schemat"
            " {version}, ta wersja zna {supported}); zainstaluj nowszą wersję"
            " Archiwisty. Baza pozostaje bez zmian."
        ),
    ),
    "migration_broken": Text(
        (
            "Migrating the state database {path} would break the links between tables;"
            " the database remains unchanged."
        ),
        (
            "Migracja bazy stanu {path} zerwałaby powiązania między tabelami; baza"
            " pozostaje bez zmian."
        ),
    ),
    "id_pattern": Text(
        (
            'Invalid identifier "{id}": lower-case letters, digits, ".", "_" and'
            ' "-", at most 64 characters, starting with a letter or a digit.'
        ),
        (
            "Niepoprawny identyfikator „{id}”: małe litery, cyfry, „.”, „_” i „-”,"
            " najwyżej 64 znaki, na początku litera albo cyfra."
        ),
    ),
    "user_id_reserved": Text(
        'The identifier "{id}" is reserved for the owner of the local installation.',
        "Identyfikator „{id}” jest zarezerwowany dla właściciela lokalnej instalacji.",
    ),
    "name_invalid": Text(
        "The name cannot be empty or longer than {limit} characters.",
        "Nazwa nie może być pusta ani dłuższa niż {limit} znaków.",
    ),
    "roles_unknown": Text(
        "Unknown roles: {roles}. Available: admin, store_writer.",
        "Nieznane role: {roles}. Dostępne: admin, store_writer.",
    ),
    "visibility_unknown": Text(
        (
            'Unknown visibility "{visibility}". Available: public, users, group,'
            " private."
        ),
        "Nieznana widoczność „{visibility}”. Dostępne: public, users, group, private.",
    ),
    "entries_users": Text(
        (
            'Visibility "users" requires a list of users (at least one) and does not'
            " accept groups."
        ),
        (
            "Widoczność „users” wymaga listy osób (co najmniej jednej) i nie przyjmuje"
            " grup."
        ),
    ),
    "entries_group": Text(
        (
            'Visibility "group" requires a list of groups (at least one) and does'
            " not accept users."
        ),
        (
            "Widoczność „group” wymaga listy grup (co najmniej jednej) i nie przyjmuje"
            " osób."
        ),
    ),
    "entries_none": Text(
        'Visibility "{visibility}" does not accept a list of users or groups.',
        "Widoczność „{visibility}” nie przyjmuje listy osób ani grup.",
    ),
    "user_exists": Text(
        'The account "{id}" already exists.',
        "Konto „{id}” już istnieje.",
    ),
    "group_exists": Text(
        'The group "{id}" already exists.',
        "Grupa „{id}” już istnieje.",
    ),
    "user_not_found": Text(
        'There is no account "{id}".',
        "Nie ma konta „{id}”.",
    ),
    "group_not_found": Text(
        'There is no group "{id}".',
        "Nie ma grupy „{id}”.",
    ),
    "last_admin": Text(
        (
            'The account "{id}" is the last enabled administrator of the team: give'
            " another account the role admin first."
        ),
        (
            "Konto „{id}” jest ostatnim włączonym administratorem zespołu: najpierw"
            " nadaj rolę admin innemu kontu."
        ),
    ),
    "users_unknown": Text(
        "Unknown accounts: {ids}.",
        "Nieznane konta: {ids}.",
    ),
    "groups_unknown": Text(
        "Unknown groups: {ids}.",
        "Nieznane grupy: {ids}.",
    ),
    "import_not_empty": Text(
        (
            "The state database {path} is not empty: a backup can only be restored"
            " into an empty database (no accounts, groups, project entries,"
            " preferences or log)."
        ),
        (
            "Baza stanu {path} nie jest pusta: kopię można odtworzyć tylko do pustej"
            " bazy (bez kont, grup, wpisów projektów, preferencji i dziennika)."
        ),
    ),
    "import_inconsistent": Text(
        "The state database backup is inconsistent: {detail}",
        "Kopia bazy stanu jest niespójna: {detail}",
    ),
    "import_not_json": Text(
        "The file is not valid JSON: {detail}",
        "Plik nie jest poprawnym JSON: {detail}",
    ),
    "import_schema": Text(
        "The file is not a backup of the state database {expected} (schema: {found}).",
        "Plik nie jest kopią bazy stanu {expected} (schemat: {found}).",
    ),
    "import_invalid": Text(
        "The state database backup has invalid fields: {fields}.",
        "Kopia bazy stanu ma niepoprawne pola: {fields}.",
    ),
}
