"""Keep the tests away from the settings and default roots of the producers.

Kartograf and IMGWTools take their settings from ``nogat.toml`` and from the
variables ``KARTOGRAF_*``, ``IMGW_*`` and ``NOGAT_*`` (DEV-18.1), and a call
that names no store root reads and writes the default root of the producer,
``<data_dir>/kartograf`` or ``<data_dir>/imgw`` (DEV-19.2). A test run on a
developer's computer would meet that computer's settings and, through one
forgotten ``root=``, write into the developer's real store.

``isolated_producers`` gives the producers the surroundings of a computer with
no settings: an empty ``nogat.toml``, every directory they would use inside a
canary tree that does not exist yet, and their default language. ``Canary.check``
fails when anything appeared in the tree, which only a call that wrote
without a store root of its own can cause (Decision 1 of the plan of
2026-10-25). ``tests/conftest.py`` applies it to every test; a test that needs
another value sets that variable itself.
"""

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

# Kartograf's own default: the tests expect its Polish texts.
LANGUAGE = "pl"
# Paths a failure names before it says how many more there are.
SHOWN = 10


@dataclass(frozen=True, slots=True)
class Canary:
    """The tree that every default directory of the producers points into.

    Parameters
    ----------
    base : Path
        Directory that stays empty. The directories the producers would use lie
        below it and do not exist, as on a computer that never ran a producer.
    settings_file : Path
        An empty ``nogat.toml`` outside ``base``: a settings file that
        ``NOGAT_CONFIG`` names and that does not exist is an error of the
        producers' commands, so "no settings" is an empty file.
    """

    base: Path
    settings_file: Path

    @property
    def data_dir(self) -> Path:
        """``data_dir`` of both producers."""
        return self.base / "data"

    @property
    def cache_dir(self) -> Path:
        """``cache_dir`` of both producers."""
        return self.base / "cache"

    @property
    def kartograf_root(self) -> Path:
        """The default store root of Kartograf (``KARTOGRAF_ROOT``)."""
        return self.base / "kartograf"

    @property
    def imgw_root(self) -> Path:
        """The default store root of IMGWTools (``IMGW_ROOT``)."""
        return self.base / "imgw"

    @property
    def imgw_reference_dir(self) -> Path:
        """The directory of IMGWTools' reference data (``IMGW_REFERENCE_DIR``)."""
        return self.base / "reference"

    def environment(self) -> dict[str, str]:
        """Return the variables that lead every default of the producers here.

        A producer's own variable beats the shared ``NOGAT_*`` one, so each
        producer's directories and language are set as well: a developer's
        ``KARTOGRAF_DATA_DIR`` would win over ``NOGAT_DATA_DIR``.
        """
        data, cache = str(self.data_dir), str(self.cache_dir)
        return {
            "NOGAT_CONFIG": str(self.settings_file),
            "NOGAT_DATA_DIR": data,
            "NOGAT_CACHE_DIR": cache,
            "NOGAT_LANG": LANGUAGE,
            "KARTOGRAF_ROOT": str(self.kartograf_root),
            "KARTOGRAF_DATA_DIR": data,
            "KARTOGRAF_CACHE_DIR": cache,
            "KARTOGRAF_LANG": LANGUAGE,
            "IMGW_ROOT": str(self.imgw_root),
            "IMGW_DATA_DIR": data,
            "IMGW_CACHE_DIR": cache,
            "IMGW_REFERENCE_DIR": str(self.imgw_reference_dir),
            "IMGW_LANG": LANGUAGE,
        }

    def appeared(self) -> list[str]:
        """Return what lies in the tree: paths relative to ``base``, sorted."""
        return sorted(
            path.relative_to(self.base).as_posix() for path in self.base.rglob("*")
        )

    def check(self) -> None:
        """Fail when anything appeared in the tree, and empty the tree.

        Raises
        ------
        pytest.fail.Exception
            A producer or a test wrote into a default directory: the call
            named no store root of its own.
        """
        found = self.appeared()
        if not found:
            return
        for entry in self.base.iterdir():
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
        more = len(found) - SHOWN
        shown = ", ".join(found[:SHOWN]) + (f" and {more} more" if more > 0 else "")
        pytest.fail(
            f"{len(found)} paths appeared in the canary tree of the producers: "
            f"{shown}. A producer wrote to a default root or directory because "
            "the call named no store root of its own: pass root= (Kartograf) or "
            'options["root"] (IMGWTools). The tree is emptied.',
            pytrace=False,
        )


@contextmanager
def isolated_producers(work: Path) -> Iterator[Canary]:
    """Run the block as on a computer without settings of the producers.

    The variables of ``Canary.environment`` are set for the block and given back
    after it, so child processes started inside inherit them; leaving the
    block checks the tree (``Canary.check``) unless an exception leaves it.

    Parameters
    ----------
    work : Path
        A directory that does not exist yet: it gets the canary tree and the
        empty settings file.

    Yields
    ------
    Canary
        The tree, to look into during the block.
    """
    base = work / "canary"
    base.mkdir(parents=True)
    settings_file = work / "settings" / "nogat.toml"
    settings_file.parent.mkdir()
    settings_file.write_text("", encoding="utf-8")
    canary = Canary(base, settings_file)
    with pytest.MonkeyPatch.context() as patch:
        for name, value in canary.environment().items():
            patch.setenv(name, value)
        yield canary
    canary.check()
