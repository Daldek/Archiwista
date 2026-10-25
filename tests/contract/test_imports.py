"""Producer libraries are imported only by their adapters, only via ``__all__``.

Upper layers know just ``archiwista.sources`` (A-ADR-014, A-ADR-019,
A-ADR-024): a producer can change its internals without breaking them, and
Archiwista starts without the optional IMGWTools. The server starts without
the libraries of the render processes (plan v0.2, decision 3).
"""

import ast
import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import kartograf
import pytest

import archiwista

PACKAGE_DIR = Path(archiwista.__file__).parent
ADAPTER_DIRS = {
    "kartograf": PACKAGE_DIR / "adapter" / "kartograf",
    "imgwtools": PACKAGE_DIR / "adapter" / "imgw",
}
# Imports every module outside the adapters with IMGWTools made unavailable,
# records whether that imported Kartograf, then loads the plugins.
START_WITHOUT_IMGWTOOLS = """
import importlib, json, pkgutil, sys
from pathlib import Path

sys.modules["imgwtools"] = None
import archiwista

names = [
    info.name
    for info in pkgutil.walk_packages(archiwista.__path__, "archiwista.")
    if not info.name.startswith("archiwista.adapter")
]
for name in names:
    importlib.import_module(name)
upper_layers = sorted(m for m in sys.modules if m.partition(".")[0] == "kartograf")
from archiwista.sources.registry import load_registry

states = load_registry(cache_dir=Path(sys.argv[1])).states()
print(json.dumps({
    "modules": names,
    "kartograf_in_upper_layers": upper_layers,
    "states": {state.producer: state.status for state in states},
}))
"""
# Libraries only render and build processes import (plan v0.2, decision 3).
PREVIEW_LIBRARIES = frozenset(
    {"rio_tiler", "laspy", "lazrs", "morecantile", "numexpr", "color_operations"}
)
# Imports what ``archiwista serve`` starts with, loads the plugins and lists
# the top-level modules imported by then.
SERVER_START = """
import json, sys
from pathlib import Path

import archiwista.app, archiwista.cli, archiwista.server
from archiwista.sources.registry import load_registry

load_registry(cache_dir=Path(sys.argv[1])).states()
print(json.dumps(sorted({name.partition(".")[0] for name in sys.modules})))
"""


def _imports(path: Path) -> Iterator[tuple[int, str, tuple[str, ...]]]:
    """Return ``(line, module, imported names)`` of each absolute import."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name, ()
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.lineno, node.module, tuple(a.name for a in node.names)


def test_producers_are_imported_only_in_their_adapters() -> None:
    """``kartograf`` and ``imgwtools`` appear only in their adapter packages."""
    misplaced = [
        f"{path.relative_to(PACKAGE_DIR)}:{line} {module}"
        for path in sorted(PACKAGE_DIR.rglob("*.py"))
        for line, module, _ in _imports(path)
        if module.partition(".")[0] in ADAPTER_DIRS
        and not path.is_relative_to(ADAPTER_DIRS[module.partition(".")[0]])
    ]

    assert misplaced == []


def test_kartograf_adapter_uses_only_public_api() -> None:
    """The adapter imports names of ``kartograf.__all__`` and nothing deeper."""
    public = set(kartograf.__all__)
    imports = [
        (f"{path.name}:{line}", module, names)
        for path in sorted(ADAPTER_DIRS["kartograf"].rglob("*.py"))
        for line, module, names in _imports(path)
        if module.partition(".")[0] == "kartograf"
    ]

    assert imports
    for place, module, names in imports:
        assert module == "kartograf" and names, f"{place}: import {module}"
        assert set(names) <= public, f"{place}: {sorted(set(names) - public)}"


def test_imgw_adapter_uses_only_public_api_and_never_pyarrow() -> None:
    """The adapter imports public names of ``imgwtools`` and never ``pyarrow``."""
    imgwtools = pytest.importorskip("imgwtools")
    public = set(imgwtools.__all__)
    imports = [
        (f"{path.name}:{line}", module, names)
        for path in sorted(ADAPTER_DIRS["imgwtools"].rglob("*.py"))
        for line, module, names in _imports(path)
        if module.partition(".")[0] in {"imgwtools", "pyarrow"}
    ]

    assert imports
    for place, module, names in imports:
        assert module == "imgwtools" and names, f"{place}: import {module}"
        assert set(names) <= public, f"{place}: {sorted(set(names) - public)}"


def test_archiwista_starts_without_imgwtools(tmp_path: Path) -> None:
    """Without IMGWTools every module imports and Kartograf stays available."""
    result = subprocess.run(
        [sys.executable, "-c", START_WITHOUT_IMGWTOOLS, str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert "archiwista.sources.registry" in report["modules"]
    assert report["kartograf_in_upper_layers"] == []
    assert report["states"]["kartograf"] == "available"


def test_server_start_imports_no_preview_library(tmp_path: Path) -> None:
    """The server and its plugins load no rio-tiler, laspy or their kin."""
    result = subprocess.run(
        [sys.executable, "-c", SERVER_START, str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert PREVIEW_LIBRARIES.isdisjoint(json.loads(result.stdout))
