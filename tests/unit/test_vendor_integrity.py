"""Vendored third-party files match their manifests byte for byte (SPEC 10.1)."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

import archiwista

PACKAGE_DIR = Path(archiwista.__file__).resolve().parent
MANIFEST_NAME = "vendor.json"
# Vendored directory -> Archiwista's own files in it (exempt from the manifest).
VENDORED_DIRS = {
    PACKAGE_DIR / "web" / "vendor": frozenset({MANIFEST_NAME}),
    PACKAGE_DIR / "api" / "swagger": frozenset({MANIFEST_NAME, "archiwista-docs.js"}),
}


def vendor_problems(root: Path, own_files: frozenset[str]) -> list[str]:
    """List the differences between a vendored directory and its manifest.

    Parameters
    ----------
    root : Path
        Directory holding the vendored files and ``vendor.json``.
    own_files : frozenset of str
        Paths relative to ``root`` of Archiwista's own files, exempt from
        the manifest.

    Returns
    -------
    list of str
        One entry per unlisted, missing or changed file and per license file
        without a sha256; empty when the directory matches the manifest.
    """
    manifest = json.loads((root / MANIFEST_NAME).read_text("utf-8"))
    expected: dict[str, str] = {}
    problems: list[str] = []
    for library in manifest["libraries"]:
        for name, entry in library["files"].items():
            expected[name] = entry["sha256"]
        if library["license_file"] not in library["files"]:
            problems.append(f"license without sha256: {library['license_file']}")
    present = {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    }
    problems += [
        f"unlisted: {name}" for name in sorted(present - own_files - expected.keys())
    ]
    for name, sha256 in sorted(expected.items()):
        path = root / name
        if not path.is_file():
            problems.append(f"missing: {name}")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
            problems.append(f"changed: {name}")
    return problems


@pytest.mark.parametrize(
    ("root", "own_files"),
    list(VENDORED_DIRS.items()),
    ids=["web-vendor", "api-swagger"],
)
def test_vendor_manifest_files_match_recorded_sha256(
    root: Path, own_files: frozenset[str]
) -> None:
    """Every vendored file is listed with its license and matches its sha256."""
    # Act
    problems = vendor_problems(root, own_files)

    # Assert
    assert problems == []


def test_vendor_manifest_flipped_byte_reported(tmp_path: Path) -> None:
    """One changed byte of a vendored file is reported as changed."""
    # Arrange
    root = tmp_path / "swagger"
    shutil.copytree(PACKAGE_DIR / "api" / "swagger", root)
    license_file = root / "LICENSE"
    data = bytearray(license_file.read_bytes())
    data[0] ^= 0x01
    license_file.write_bytes(bytes(data))

    # Act
    problems = vendor_problems(root, VENDORED_DIRS[PACKAGE_DIR / "api" / "swagger"])

    # Assert
    assert problems == ["changed: LICENSE"]


def test_vendor_manifest_unlisted_file_reported(tmp_path: Path) -> None:
    """A file added next to the vendored ones without a manifest entry is reported."""
    # Arrange
    root = tmp_path / "vendor"
    shutil.copytree(PACKAGE_DIR / "web" / "vendor", root)
    (root / "htm" / "extra.mjs").write_text("export {};\n", "utf-8")

    # Act
    problems = vendor_problems(root, VENDORED_DIRS[PACKAGE_DIR / "web" / "vendor"])

    # Assert
    assert problems == ["unlisted: htm/extra.mjs"]
