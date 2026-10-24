"""The commands of the README examples run (DOC-2.6).

Every command in a fenced shell block of ``README.md`` is run here in a fresh
user profile, checked against the command's options, or listed in ``NOT_RUN``
with the reason it cannot run offline in the gate. A command this test does not
know fails it, so an example cannot be added that nobody runs.
"""

import json
import re
import shlex
import socket
from pathlib import Path

import pytest

from archiwista.cli import main
from archiwista.config import AppPaths
from tests.fixtures.local_server import local_paths

README = Path(__file__).resolve().parents[2] / "README.md"
FENCE = re.compile(r"^```(?:bash|sh|shell)\n(.*?)^```", re.DOTALL | re.MULTILINE)
ENV_ASSIGNMENT = re.compile(r"[A-Z_][A-Z0-9_]*=\S*")
# Commands of the examples that are not run, by their first words, and why.
NOT_RUN = {
    ("uv", "sync"): "builds the environment the tests run in",
    ("uv", "run", "playwright"): "downloads a browser",
    ("scripts/gate.sh",): "is the gate that runs this test",
}
# Commands that serve until stopped (``tests/integration/test_serve.py`` starts
# them): here only the options of the example must exist.
SERVING = ("serve",)


def examples() -> list[list[str]]:
    """Return the commands of the shell blocks of the README, as lists of words."""
    commands = []
    for block in FENCE.findall(README.read_text(encoding="utf-8")):
        for line in block.replace("\\\n", " ").splitlines():
            words = shlex.split(line, comments=True)
            while words and ENV_ASSIGNMENT.fullmatch(words[0]):
                del words[0]
            if words:
                commands.append(words)
    return commands


def archiwista_arguments(words: list[str]) -> list[str] | None:
    """Return the arguments of an ``archiwista`` command, or None for another one."""
    if words[:2] == ["uv", "run"]:
        words = words[2:]
    return words[1:] if words[:1] == ["archiwista"] else None


EXAMPLES = examples()
OWN = [words for words in EXAMPLES if archiwista_arguments(words) is not None]
FOREIGN = [words for words in EXAMPLES if archiwista_arguments(words) is None]
SERVED = [words for words in OWN if (archiwista_arguments(words) or [""])[0] in SERVING]
RUNNABLE = [words for words in OWN if words not in SERVED]


def free_port() -> int:
    """Return a port nothing listens on, for the profile's server setting."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def profile(tmp_path: Path) -> AppPaths:
    """Give a new user profile whose server port is free, for ``doctor``."""
    paths = local_paths(tmp_path)
    paths.config_file.parent.mkdir(parents=True)
    paths.config_file.write_text(f"port = {free_port()}\n", encoding="utf-8")
    return paths


def test_readme_shows_archiwista_commands() -> None:
    """The fences are found: the README has examples this module can run."""
    assert OWN


@pytest.mark.parametrize("words", FOREIGN, ids=" ".join)
def test_readme_example_that_is_not_run_is_known(words: list[str]) -> None:
    """A command other than ``archiwista`` is one the test knows it cannot run."""
    known = [prefix for prefix in NOT_RUN if tuple(words[: len(prefix)]) == prefix]
    assert known, f"decide whether the test can run: {shlex.join(words)}"


@pytest.mark.parametrize("words", RUNNABLE, ids=" ".join)
def test_readme_example_runs_in_a_fresh_profile(
    words: list[str], profile: AppPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    """An ``archiwista`` example ends with status 0, and ``--json`` prints JSON."""
    # Arrange
    arguments = archiwista_arguments(words) or []

    # Act
    status = main(arguments, paths=profile)

    # Assert
    captured = capsys.readouterr()
    assert status == 0, captured.err
    if "--json" in arguments:
        json.loads(captured.out)


@pytest.mark.parametrize("words", SERVED, ids=" ".join)
def test_readme_serving_example_uses_options_the_command_has(
    words: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """The options of an example that serves are in the command's own help."""
    # Arrange
    arguments = archiwista_arguments(words) or []
    options = [word.split("=")[0] for word in arguments if word.startswith("--")]

    # Act
    with pytest.raises(SystemExit) as stop:
        main([arguments[0], "--help"])

    # Assert
    assert stop.value.code == 0
    help_text = capsys.readouterr().out
    assert [option for option in options if option not in help_text] == []
