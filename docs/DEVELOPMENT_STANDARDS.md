# DEVELOPMENT_STANDARDS.md - Standardy Kodowania

## Archiwista - aplikacja webowa do pracy z magazynem danych

**Wersja:** 1.0 (na podstawie standardów IMGWTools 1.1)
**Data:** 2026-10-18

Standardy obowiązują od pierwszego kodu (plan v0.1). Architektura: SPEC 5,
A-ADR-004..008, 013, 015, 028.

---

## 0. Język

Projekt jest skierowany na polski rynek, ale **kod i wszystko, co go opisuje,
jest po angielsku**:

| Element | Język |
|---------|-------|
| Identyfikatory (moduły, klasy, funkcje, zmienne, klucze JSON, ścieżki API HTTP) | angielski |
| Docstringi, komentarze, komunikaty w logach, nazwy testów | angielski |
| Pliki dla kontrybutorów (`CONTRIBUTING.md`, `CONTRIBUTORS.md`, szablon pull requestu) | angielski |
| Teksty interfejsu i komunikaty błędów API dla użytkownika (`message`) | polski — w jednym słowniku tekstów |
| Komunikaty producentów (Kartograf, IMGWTools) | bez zmian, tak jak je podał producent |
| Dokumentacja projektu (`docs/`, `README.md`) | polski |
| Opisy commitów (Conventional Commits) | polski (CLAUDE.md) |

---

## 1. Nazewnictwo

### 1.1 Python

```python
# Zmienne i funkcje: snake_case, jednostka w nazwie (jak w rodzinie projektów)
version_sha256 = "f3015407c5cc85f9..."
area_m2 = 120_000_000.0
size_bytes = 37_004_903

def iter_entries(root: Path, *, scope: Scope | None = None) -> Iterator[StoreEntry]:
    pass

# Klasy: PascalCase
class StoreEntry:
    pass

class CoverageLabel:
    pass

# Stałe: UPPER_SNAKE_CASE
DEFAULT_PORT = 8090
PREVIEW_CACHE_LIMIT_BYTES = 20 * 1024**3
```

### 1.2 Konwencje nazewnicze

| Wzorzec | Znaczenie | Przykład |
|---------|-----------|----------|
| `iter_*` | Przejście po magazynie lub indeksie (generator) | `iter_entries()` |
| `read_*` | Odczyt bez zapisu (przez API producenta albo indeks) | `read_meta()` |
| `check_*` | Sprawdzenie bez zapisu — bliźniak działania zapisującego (jak w Kartografie) | `check_command()` |
| `run_*` | Działanie, wyłącznie w procesie roboczym | `run_command()` |
| `scan_*` | Budowa lub odświeżenie indeksu | `scan_store()` |
| `make_*` | Utworzenie pliku na polecenie użytkownika (katalog projektu) | `make_snapshot()` |
| `*Entry` | Wpis magazynu lub indeksu | `StoreEntry` |
| `*Plan` | Plan działania pokazany w „Oknie planu” | `DownloadPlan` |
| `*Event` | Zdarzenie zadania w tle (postęp, komunikat) | `JobEvent` |
| `*Error` | Wyjątek | `SourceUnavailableError` |

---

## 2. Formatowanie

### 2.1 Ruff (88 znaków)

```python
# Maksymalna długość linii: 88 znaków
# Wcięcia: 4 spacje
# Formatter: ruff format

# DOBRZE
def check_command(
    command: str,
    options: dict[str, object],
    *,
    store: Store,
    cancel: Callable[[], bool] | None = None,
) -> UpdatePlan:
    pass

# ŹLE (za długa linia)
def check_command(command: str, options: dict[str, object], *, store: Store, cancel: Callable[[], bool] | None = None) -> UpdatePlan:
    pass
```

### 2.2 Importy

```python
# Kolejność: stdlib → third-party → local
# Alfabetycznie w grupach
# Puste linie między grupami

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from archiwista.index import Index
from archiwista.sources import SourceAdapter
```

**Zasada producentów:** `kartograf` importuje wyłącznie
`archiwista/adapter/kartograf/`, a `imgwtools` wyłącznie
`archiwista/adapter/imgw/` — i tylko z publicznego API (`__all__`). Pilnuje
tego test importów (SPEC 11, A-ADR-019, A-ADR-024).

---

## 3. Type Hints

### 3.1 Wymagane wszędzie

```python
def read_meta(
    entry: StoreEntry,
    *,
    tolerant: bool = True,
) -> EntryMeta:
    """Read the metadata envelope of a store entry."""
    pass

class EntryMeta:
    dataset: str  # Producer dataset key, e.g. "pl.gugik.nmt_1m"
    label: str  # Version label, e.g. "2023-09-08_78992"
    size_bytes: int
    source_files: list[str]  # Input versions of derived products
```

### 3.2 Python 3.12+ style

```python
# Używaj nowoczesnej składni (bez `from __future__ import annotations`)
def group_by_year(entries: list[StoreEntry]) -> dict[int, list[StoreEntry]]:
    pass

# Union type z |
def find_entry(sha256: str | None = None) -> StoreEntry | None:
    pass
```

---

## 4. Docstrings (NumPy Style, English)

### 4.1 Funkcje

```python
def make_snapshot(
    path: Path,
    *,
    project: Project,
    note: str = "",
    cancel: Callable[[], bool] | None = None,
) -> Snapshot:
    """
    Copy an own-data file into the project's snapshot folder.

    Parameters
    ----------
    path : Path
        Working file in the project's data folder.
    project : Project
        Project the data folder belongs to.
    note : str, optional
        Description stored in ``migawka.json``.
    cancel : callable, optional
        Polled between files; ``True`` stops without a partial snapshot.

    Returns
    -------
    Snapshot
        The new snapshot, or the last one when the content is unchanged.

    Raises
    ------
    PathOutsideRootError
        If ``path`` is not inside the project's data folder.
    SnapshotError
        If the consistent copy or the atomic publication fails.

    Examples
    --------
    >>> snap = make_snapshot(project.data_dir / "kanalizacja.gpkg", project=project)
    >>> snap.label
    '2026-10-18_471d37c0'
    """
    pass
```

### 4.2 Klasy

```python
class StoreEntry:
    """
    One file of a producer store as seen by the index.

    Parameters
    ----------
    source : str
        Source adapter name, e.g. "kartograf".
    segment : str
        Product segment, e.g. "nmt/pl_1992_1m_evrf2007".
    path : Path
        Version path inside the store.
    sha256 : str
        Content hash (version identity).

    Attributes
    ----------
    problem : str or None
        Store problem found by the producer (orphan, leftover, unreadable).

    Examples
    --------
    >>> entry = next(adapter.iter_entries(root))
    >>> print(f"{entry.segment}: {entry.path.name}")
    """
    pass
```

### 4.3 Interfejs (JavaScript)

- Preact + htm, moduły ES **bez kroku budowania** i bez Node.js
  (A-ADR-028); biblioteki (Preact, htm, MapLibre) dołączone do pakietu
  w `archiwista/web/vendor/`, nigdy z CDN.
- Nazewnictwo: `camelCase` dla zmiennych i funkcji, `PascalCase` dla
  komponentów, `UPPER_SNAKE_CASE` dla stałych.
- Opisy w JSDoc po angielsku; typy w JSDoc dla funkcji publicznych modułu
  (zastępują kontrolę typów, której nie ma bez kroku budowania).
- Teksty interfejsu tylko ze słownika tekstów (polski), nigdy wpisane
  w komponent.
- Stan widoku w adresie URL (obszar, produkt, filtry, widok mapy).

```javascript
/**
 * Coverage label of a year variant (docs/SPEC.md 6.4).
 *
 * @param {Variant} variant - Year variant from the availability report.
 * @returns {{kind: "full" | "multi" | "partial" | "none", text: string}}
 */
export function coverage(variant) {
  // ...
}
```

---

## 5. Testowanie

### 5.1 Struktura testów

```
tests/
├── unit/
│   ├── test_index.py        # Indeks: schemat, skan, zapytania
│   ├── test_coverage.py     # Etykiety pokrycia (SPEC 6.4)
│   ├── test_snapshots.py    # Migawki danych własnych (A-ADR-027)
│   └── test_security.py     # Host, token, CSRF, ścieżki (SPEC 10.1)
├── integration/
│   └── test_api.py          # Endpointy /api/v1
├── contract/
│   └── test_imports.py      # Producenci tylko w adapterach
├── e2e/
│   └── test_ui.py           # Playwright: przepływy interfejsu
├── fixtures/
│   └── make_store.py        # Generator magazynu testowego
└── conftest.py              # Shared fixtures

# Markery: live (sieć i prawdziwe usługi), perf (magazyn syntetyczny
# 50 000 slotów), smb (prawdziwy udział SMB) — domyślnie wyłączone.
```

### 5.2 Nazewnictwo testów

```python
# test_<moduł>_<funkcja>_<scenariusz>

def test_coverage_label_two_campaigns_complete():
    """Complete only with full sheets of two campaigns reads 'pełne · 2 kampanie'."""
    pass

def test_snapshot_same_content_creates_nothing():
    """A second snapshot of unchanged content returns the previous one."""
    pass

def test_security_foreign_host_rejected():
    """A request with a foreign Host header is rejected (DNS rebinding)."""
    pass
```

### 5.3 AAA Pattern

```python
def test_snapshot_interrupted_leaves_no_partial_version(tmp_path):
    # Arrange
    project = make_project(tmp_path, files={"dane/kanalizacja.gpkg": GPKG_BYTES})

    # Act
    with pytest.raises(SnapshotCancelled):
        make_snapshot(project.data_dir / "kanalizacja.gpkg", project=project, cancel=lambda: True)

    # Assert
    assert list((project.data_dir / ".wersje").glob("*/*")) == []
```

### 5.4 Pokrycie

Stan faktyczny: brak kodu (stan na 2026-10-18).
Cel: **80%**, bramka `--cov-fail-under=80` włączona od pierwszego kodu (v0.1).

```bash
.venv/bin/python -m pytest -m "not live" --cov=archiwista --cov-report=html --cov-fail-under=80
```

---

## 6. Git Workflow

### 6.1 Branching

```
main          # Stabilna wersja (wydania)
develop       # Aktywny rozwój (DOMYŚLNA GAŁĄŹ ROBOCZA)
feat/*        # Nowe funkcjonalności (krótkotrwałe, z develop)
fix/*         # Poprawki błędów (krótkotrwałe, z develop)
```

**WAŻNE:** Cały rozwój kodu odbywa się na gałęzi `develop` albo na
krótkotrwałej gałęzi z `develop`. Gałąź `main` otrzymuje tylko merge
z `develop` przy wydaniach. Repozytorium bez remote — bez `push`.

### 6.2 Tagowanie

```bash
# Tworzenie tagu wersji (lokalnie)
git tag -a v0.1.0 -m "Release v0.1.0: data viewer"
```

### 6.3 Conventional Commits

```bash
# Format (opis po polsku; autor Daldek <git@debever.pl>, bez stopki Co-Authored-By)
<type>(<scope>): <description>

# Typy
feat     # Nowa funkcjonalność
fix      # Poprawka błędu
docs     # Dokumentacja
test     # Testy
refactor # Refaktoryzacja
chore    # Inne (config, deps)

# Przykłady
feat(index): skan przyrostowy magazynu Kartografa
fix(api): kod source_unavailable przy braku IMGWTools
docs(spec): doprecyzowanie etykiet pokrycia
test(snapshots): przerwanie migawki bez częściowej wersji
```

---

## 7. Struktura modułów

### 7.1 Powierzchnia publiczna

Archiwista jest aplikacją, nie biblioteką. Publiczne są: API HTTP
`/api/v1` (SPEC 9), komenda `archiwista` (`serve`, `reindex`, `doctor`) oraz
interfejs źródła dla wtyczek (grupa entry points `archiwista.sources`,
A-ADR-024).

```python
# archiwista/sources/__init__.py
"""Source interface for store producer adapters (plugins)."""

from archiwista.sources.protocol import SourceAdapter
from archiwista.sources.types import EntryMeta, Footprint, StoreEntry

__all__ = [
    "EntryMeta",
    "Footprint",
    "SourceAdapter",
    "StoreEntry",
]
```

### 7.2 Importuj przez publiczne API

```python
# DOBRZE - wtyczka i warstwy wyżej używają interfejsu źródła
from archiwista.sources import SourceAdapter, StoreEntry

# DOBRZE - adapter używa publicznego API producenta (kartograf.__all__)
from kartograf import iter_store  # KA-1, proposed (SPEC 12.1)

# Unikaj - wewnętrzny moduł producenta (łamie A-ADR-014)
from kartograf.download.storage import content_segment
```

---

## 8. Error Handling

### 8.1 Hierarchia wyjątków

```python
# archiwista/errors.py

class ArchiwistaError(Exception):
    """Base exception for Archiwista."""
    pass

class SourceUnavailableError(ArchiwistaError):
    """Producer package not installed or store directory unreachable."""
    pass

class SourceIncompatibleError(ArchiwistaError):
    """Producer version or store schema outside the supported range."""
    pass

class PathOutsideRootError(ArchiwistaError):
    """Path not inside a configured store or project root."""
    pass

class SnapshotError(ArchiwistaError):
    """Own-data snapshot could not be made consistently."""
    pass
```

Wyjątki producentów (`KartografError`, `IMGWError`) łapie tylko adapter;
ich tekst trafia do użytkownika bez zmian (PRD N1.3). API HTTP zamienia
wyjątek na kod (`source_unavailable`, `source_incompatible`, `not_found`,
`conflict`…) i polski komunikat (SPEC 9.1).

### 8.2 Walidacja na wejściu

```python
def resolve_store_path(path: Path, *, roots: list[Path]) -> Path:
    """Resolve a requested path and require it inside a configured root."""
    # Only paths known to the index; symlinks leaving the root are rejected (SPEC 10.1)
    real = path.resolve(strict=True)
    if not any(real.is_relative_to(root) for root in roots):
        raise PathOutsideRootError(f"{path} is outside the configured roots")

    return real
```

---

## 9. Komendy

```bash
# Testy (bez sieci)
.venv/bin/python -m pytest -m "not live"

# Testy z pokryciem
.venv/bin/python -m pytest -m "not live" --cov=archiwista --cov-report=html

# Testy interfejsu (Playwright, przeglądarka instalowana raz)
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest tests/e2e

# Formatowanie
.venv/bin/ruff format archiwista/ tests/

# Sprawdzenie formatowania
.venv/bin/ruff format archiwista/ tests/ --check

# Linting
.venv/bin/ruff check archiwista/ tests/

# Type checking (bez Node.js; SPEC 11)
.venv/bin/mypy archiwista/ tests/
```

---

## 10. Checklist przed commitem

- [ ] Testy przechodzą (`pytest -m "not live"`), także testy interfejsu przy zmianach w `archiwista/web/`
- [ ] Pokrycie nie spada poniżej 80% (`pytest --cov`)
- [ ] Formatowanie OK (`ruff format --check`)
- [ ] Linting OK (`ruff check`)
- [ ] Type hints OK (`mypy`)
- [ ] Docstrings NumPy dla publicznych funkcji/klas (wymuszane przez ruff `D`)
- [ ] Kod, komentarze i docstringi po angielsku; teksty interfejsu tylko w słowniku (sekcja 0)
- [ ] Producenci importowani tylko w adapterach (test importów zielony)
- [ ] SPEC, DECISIONS i PROGRESS.md zaktualizowane, jeśli zmiana tego wymaga

---

**Wersja dokumentu:** 1.0
**Data ostatniej aktualizacji:** 2026-10-18
