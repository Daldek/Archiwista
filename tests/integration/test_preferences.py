"""Each person's own preferences and path aliases (plan v0.4 T11, C12, ADR-047).

``GET`` and ``PUT /preferences`` read and replace the preferences of the
session's principal and of no one else: a person's, an agent's account's, the
local owner's in local mode. A path alias is validated (an absolute prefix on
the server, at most 20 of them) and changes only ``personal`` of the copy
paths a person is shown: no route reaches a file through one. How the year
types number the station routes is ``test_year_types.py``'s (it needs
IMGWTools).
"""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

import pytest

from archiwista.auth import LOCAL_OWNER, LOCAL_PRINCIPAL_ID
from tests.fixtures.api_session import Api, Caller, assert_problem
from tests.fixtures.api_store import STORE, ServedStore, served_store
from tests.fixtures.own_data_api import own_data_api
from tests.fixtures.permissions import (
    OWNER,
    add_people,
    last_entry,
    log_entries,
    principal,
    share,
)

pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")

DEFAULTS: dict[str, Any] = {
    "year_types": {"hydro": "hydrological", "meteo": "calendar"},
    "basemap": None,
    "path_aliases": [],
}
NAS = {"server": "/mnt/nas/", "personal": "Y:\\"}


@dataclass(frozen=True)
class People:
    """The served store with the local owner, two people and an agent of one."""

    served: ServedStore
    olga: Caller
    igor: Caller
    agent: Caller

    @property
    def api(self) -> Api:
        """The running application."""
        return self.served.api

    @property
    def owner(self) -> Caller:
        """The local owner's session."""
        return self.served.owner

    def callers(self) -> tuple[Caller, ...]:
        """Every session of the module."""
        return (self.owner, self.olga, self.igor, self.agent)


def _json(caller: Caller, path: str) -> Any:
    """Return the body of ``caller``'s ``200`` answer of ``GET path``."""
    response = caller.request("GET", path)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture(scope="module")
def served(tmp_path_factory: pytest.TempPathFactory) -> Iterator[People]:
    """Serve a scanned store to the local owner, olga, igor and olga's agent."""
    with served_store(tmp_path_factory.mktemp("preferences")) as found:
        state = found.api.state
        add_people(state)
        olga = principal(state, "owner")
        yield People(
            found,
            found.api.session(olga),
            found.api.session(principal(state, "other")),
            found.api.session(olga, token="agent"),
        )


@pytest.fixture
def people(served: People) -> Iterator[People]:
    """Return the served people; everyone has the defaults again afterwards."""
    yield served
    for caller in served.callers():
        reset = caller.request("PUT", "/preferences", json={})
        assert reset.status_code == 200, reset.text


def test_preferences_each_person_reads_and_replaces_only_their_own(
    people: People,
) -> None:
    """A change is the session's own: the others keep theirs, nothing is logged."""
    # Arrange
    chosen = {
        "year_types": {"hydro": "calendar", "meteo": "hydrological"},
        "basemap": "",
        "path_aliases": [NAS],
    }
    after = last_entry(people.api.state)

    # Act
    saved = people.olga.request("PUT", "/preferences", json=chosen)
    hers = _json(people.olga, "/preferences")
    his = _json(people.igor, "/preferences")
    owners = _json(people.owner, "/preferences")
    replaced = people.olga.request("PUT", "/preferences", json={"basemap": None})

    # Assert
    assert saved.status_code == 200, saved.text
    assert saved.json() == hers == chosen
    assert his == owners == DEFAULTS
    assert replaced.status_code == 200, replaced.text
    assert replaced.json() == DEFAULTS
    stored = people.api.state.preferences(OWNER)
    assert stored is not None and stored.document == DEFAULTS
    assert log_entries(people.api.state, after=after) == []


def test_preferences_an_agent_has_its_account_s(people: People) -> None:
    """An agent reads and replaces the preferences of the account it acts for."""
    # Act
    changed = people.agent.request("PUT", "/preferences", json={"path_aliases": [NAS]})
    hers = _json(people.olga, "/preferences")
    agents = _json(people.agent, "/preferences")
    his = _json(people.igor, "/preferences")

    # Assert
    assert changed.status_code == 200, changed.text
    assert hers == agents == {**DEFAULTS, "path_aliases": [NAS]}
    assert his == DEFAULTS


def test_preferences_of_the_local_owner_are_the_principal_local_s(
    people: People,
) -> None:
    """In local mode the owner's preferences are kept as those of ``local``."""
    # Act
    saved = people.owner.request("PUT", "/preferences", json={"basemap": ""})

    # Assert
    assert saved.status_code == 200, saved.text
    stored = people.api.state.preferences(LOCAL_PRINCIPAL_ID)
    assert stored is not None
    assert stored.document == saved.json() == {**DEFAULTS, "basemap": ""}
    assert _json(people.served.api.session(LOCAL_OWNER), "/preferences") == (
        stored.document
    )


@pytest.mark.parametrize(
    ("body", "pointer"),
    [
        ({"path_aliases": [{"server": "mnt/nas/", "personal": "Y:\\"}]}, "server"),
        ({"path_aliases": [{"server": "/mnt/nas/", "personal": "  "}]}, "personal"),
        (
            {"path_aliases": [{"server": "/" + "n" * 400, "personal": "Y:\\"}]},
            "server",
        ),
        ({"path_aliases": [NAS] * 21}, "path_aliases"),
        ({"year_types": {"hydro": "lunar"}}, "hydro"),
    ],
    ids=["relative", "blank", "too_long", "over_20", "year_type"],
)
def test_preferences_invalid_change_is_refused_and_keeps_the_saved_ones(
    people: People, body: dict[str, Any], pointer: str
) -> None:
    """A relative or blank prefix, one over 400 characters, a 21st alias: ``400``."""
    # Arrange
    kept = {**DEFAULTS, "path_aliases": [NAS] * 20}
    first = people.olga.request("PUT", "/preferences", json=kept)

    # Act
    refused = people.olga.request("PUT", "/preferences", json=body)

    # Assert
    assert first.status_code == 200, first.text
    assert_problem(refused, 400, "validation_error", "invalid_request")
    assert refused.json()["errors"][0]["pointer"].endswith(pointer)
    assert _json(people.olga, "/preferences") == kept


def test_preferences_unknown_basemap_is_refused_with_the_configured_ones(
    people: People,
) -> None:
    """A basemap the settings do not configure: ``400 unknown_basemap``."""
    # Arrange
    names = [item["name"] for item in _json(people.owner, "/settings")["basemaps"]]

    # Act
    refused = people.olga.request("PUT", "/preferences", json={"basemap": "Mars"})
    chosen = people.olga.request("PUT", "/preferences", json={"basemap": names[-1]})

    # Assert
    assert_problem(refused, 400, "validation_error", "unknown_basemap")
    assert refused.json()["details"]["basemaps"] == names
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["basemap"] == names[-1]


def test_preferences_personal_path_of_a_file_card_follows_the_first_alias(
    people: People,
) -> None:
    """The first alias whose server prefix holds a path gives ``personal``."""
    # Arrange
    store = people.served.store
    row = _json(people.owner, "/slots?product=nmt&limit=1")["items"][0]
    card_url = f"/stores/{STORE}/slots/{row['slot']}"
    aliases = [
        {"server": "/inny/serwer/", "personal": "Q:\\"},
        {"server": f"{store.base}/", "personal": "Y:\\dane"},
        {"server": f"{store.root}/", "personal": "/home/olga/magazyn/"},
    ]
    saved = people.olga.request("PUT", "/preferences", json={"path_aliases": aliases})

    # Act
    card = _json(people.olga, card_url)
    version = _json(people.olga, f"/stores/{STORE}/versions/{card['current']}")
    theirs = _json(people.igor, card_url)

    # Assert
    assert saved.status_code == 200, saved.text
    paths = card["paths"]
    below = Path(paths["local"]).relative_to(store.base).parts
    assert paths["personal"] == str(PureWindowsPath("Y:\\dane", *below))
    assert theirs["paths"] == {**paths, "personal": None}
    below = Path(version["paths"]["local"]).relative_to(store.base).parts
    assert version["paths"]["personal"] == str(PureWindowsPath("Y:\\dane", *below))


def test_preferences_own_file_paths_follow_the_alias_and_no_route_reads_one(
    tmp_path: Path,
) -> None:
    """An own file's copy paths go through the alias; ``data-dir`` takes no alias."""
    with own_data_api(tmp_path, first=("txt",), second=()) as served:
        # Arrange
        project = served.first
        share(served.api.state, project.access_key, "public")
        igor = served.caller("other")
        text = project.folder.file("txt")
        folder = tmp_path / "dane-projektu"
        folder.mkdir()
        (folder / "opis.txt").write_text("Nowy folder danych.\n", encoding="utf-8")
        mine = "/home/ola/praca"
        aliases = [{"server": f"{tmp_path}/", "personal": f"{mine}/"}]
        saved = served.owner.request(
            "PUT", "/preferences", json={"path_aliases": aliases}
        )
        address = f"/projects/{project.key}/data-dir"

        # Act
        card = _json(served.owner, project.url(text.path))
        listed = _json(served.owner, f"/projects/{project.key}/files")
        theirs = _json(igor, project.url(text.path))
        through_alias = served.owner.request(
            "PUT", address, json={"path": f"{mine}/dane-projektu"}
        )
        unchanged = _json(served.owner, f"/projects/{project.key}/files")
        on_the_server = served.owner.request("PUT", address, json={"path": str(folder)})

    # Assert
    assert saved.status_code == 200, saved.text
    below = Path(card["paths"]["local"]).relative_to(tmp_path).as_posix()
    assert card["paths"]["personal"] == f"{mine}/{below}"
    assert listed["folder"]["path"]["personal"] == (
        f"{mine}/{project.root.relative_to(tmp_path).as_posix()}"
    )
    assert theirs["paths"] == {**card["paths"], "personal": None}
    assert_problem(through_alias, 400, "validation_error", "invalid_settings")
    problems = through_alias.json()["details"]["problems"]
    assert [problem["code"] for problem in problems] == ["own_data_dir_missing"]
    assert unchanged["folder"]["path"] == listed["folder"]["path"]
    assert on_the_server.status_code == 200, on_the_server.text
    assert on_the_server.json()["path"] == {
        "local": str(folder),
        "aliases": [],
        "personal": f"{mine}/dane-projektu",
    }
