"""Package data reaches the installed package (DEV-5.4).

The files are read through ``importlib.resources``, as an installed wheel is
read, and the patterns of ``[tool.setuptools.package-data]`` are matched against
the source tree. A checkout holds every file whatever the patterns say, so a
pattern that stops matching a kind of file, the defect that reaches users who
install a wheel, fails here and nowhere else. The source tree and
``pyproject.toml`` are found from this file, never through the installed package
(REL-2.5): a wheel holds no repository.
"""

import json
import re
import tomllib
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO / "src" / "archiwista"
PACKAGE_DATA: dict[str, list[str]] = tomllib.loads(
    (REPO / "pyproject.toml").read_text(encoding="utf-8")
)["tool"]["setuptools"]["package-data"]
MANIFEST = "vendor.json"
# Files of the package Archiwista wrote itself, next to the vendored ones.
SWAGGER_OWN_FILES = ("archiwista-docs.js", MANIFEST)


def shipped(package: str) -> set[str]:
    """Return the files of ``package`` that the package-data patterns match.

    Parameters
    ----------
    package : str
        Dotted name of a package with an entry in ``package-data``.

    Returns
    -------
    set of str
        Paths relative to the package directory, with ``/`` separators.
    """
    root = PACKAGE_DIR.joinpath(*package.split(".")[1:])
    return {
        path.relative_to(root).as_posix()
        for pattern in PACKAGE_DATA[package]
        for path in root.glob(pattern)
        if path.is_file()
    }


def listed_files(folder: Traversable) -> list[str]:
    """Return the files a ``vendor.json`` in ``folder`` lists, as it lists them."""
    manifest = json.loads(folder.joinpath(MANIFEST).read_text(encoding="utf-8"))
    return [name for library in manifest["libraries"] for name in library["files"]]


def test_files_the_page_loads_are_shipped_and_readable() -> None:
    """The page, its entry module and its styles ship as package data."""
    # Arrange
    web = resources.files("archiwista.web")
    page = web.joinpath("index.html").read_text(encoding="utf-8")

    # Act
    loaded = re.findall(r'(?:src|href)="/static/([^"]+)"', page)

    # Assert
    assert "src/main.js" in loaded
    assert set(loaded) <= shipped("archiwista.web")
    for name in loaded:
        assert web.joinpath(name).read_bytes(), name


def test_vendored_interface_libraries_are_shipped_and_readable() -> None:
    """Preact, htm, MapLibre and the glyphs ship with their licenses."""
    # Arrange
    vendor = resources.files("archiwista.web").joinpath("vendor")

    # Act
    names = listed_files(vendor)

    # Assert
    assert "preact/preact.mjs" in names
    assert {f"vendor/{name}" for name in names} <= shipped("archiwista.web")
    for name in names:
        assert vendor.joinpath(name).read_bytes(), name


def test_swagger_ui_files_are_shipped_and_readable() -> None:
    """The local Swagger UI of ``/api/docs`` ships with its license and page script."""
    # Arrange
    swagger = resources.files("archiwista.api").joinpath("swagger")

    # Act
    names = [*listed_files(swagger), *SWAGGER_OWN_FILES]

    # Assert
    assert "swagger-ui-bundle.js" in names
    assert {f"swagger/{name}" for name in names} <= shipped("archiwista.api")
    for name in names:
        assert swagger.joinpath(name).read_bytes(), name
