"""Where ``archiwista serve`` may listen: local mode, team mode with TLS or proxies.

ADR-046 decision 2, SPEC 10.2: every refusal of ``team_refusal`` as a table of
settings and ``--host`` addresses.
"""

from collections.abc import Mapping

import pytest
from cryptography.hazmat.primitives import serialization

from archiwista.config import AppSettings, parse_settings
from archiwista.messages import message
from archiwista.server import team_refusal
from tests.fixtures.team_server import team_tls

ORIGIN = "https://archiwista.firma.local"
TLS = {"tls_cert": "{cert}", "tls_key": "{key}"}
LAN_PROXIES = {"trusted_proxies": ["10.0.0.2"]}
LOOPBACK_PROXIES = {"trusted_proxies": ["127.0.0.1", "::1"]}
MIXED_PROXIES = {"trusted_proxies": ["127.0.0.1", "10.0.0.0/24"]}


@pytest.fixture(scope="module")
def files(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """Return TLS files that load, and files of each kind that do not."""
    directory = tmp_path_factory.mktemp("tls")
    tls = team_tls(directory)
    other = team_tls(directory / "other")
    garbage = directory / "garbage.pem"
    garbage.write_text("not a certificate\n", encoding="utf-8")
    key = serialization.load_pem_private_key(tls.key.read_bytes(), password=None)
    encrypted = directory / "encrypted.pem"
    encrypted.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(b"haslo-do-klucza"),
        )
    )
    return {
        "cert": str(tls.cert),
        "key": str(tls.key),
        "other_key": str(other.key),
        "garbage": str(garbage),
        "encrypted_key": str(encrypted),
        "missing": str(directory / "missing.pem"),
    }


def settings(team: Mapping[str, object] | None, files: dict[str, str]) -> AppSettings:
    """Return local settings for ``None``, else team mode with ``team`` filled in."""
    if team is None:
        return AppSettings()
    table: dict[str, object] = {"enabled": True, "origin": ORIGIN}
    for name, value in team.items():
        table[name] = value.format(**files) if isinstance(value, str) else value
    return parse_settings({"team": table})


@pytest.mark.parametrize(
    ("team", "host", "reason"),
    [
        (None, "127.0.0.1", None),
        (None, "0.0.0.0", "host_refused"),
        (None, "::", "host_refused"),
        (None, "10.0.0.5", "host_refused"),
        (None, "::1", "host_refused"),
        (None, "localhost", "host_refused"),
        ({}, "127.0.0.1", "tls_required"),
        ({}, "0.0.0.0", "tls_required"),
        (TLS, "0.0.0.0", None),
        (TLS, "::", None),
        (TLS, "10.0.0.5", None),
        (TLS, "127.0.0.1", None),
        ({**TLS, **LOOPBACK_PROXIES}, "0.0.0.0", None),
        (TLS, "archiwista.firma.local", "host_refused"),
        ({**LAN_PROXIES}, "localhost", "host_refused"),
        ({"tls_cert": "{cert}", "tls_key": "{other_key}"}, "0.0.0.0", "tls_unusable"),
        ({"tls_cert": "{garbage}", "tls_key": "{key}"}, "0.0.0.0", "tls_unusable"),
        ({"tls_cert": "{missing}", "tls_key": "{key}"}, "0.0.0.0", "tls_unusable"),
        ({"tls_cert": "{cert}", "tls_key": "{encrypted_key}"}, "::", "tls_unusable"),
        (LAN_PROXIES, "0.0.0.0", "proxy_bind_wildcard"),
        (LAN_PROXIES, "::", "proxy_bind_wildcard"),
        (LAN_PROXIES, "10.0.0.5", None),
        (LAN_PROXIES, "127.0.0.1", None),
        (LOOPBACK_PROXIES, "0.0.0.0", "proxy_bind_wildcard"),
        (LOOPBACK_PROXIES, "10.0.0.5", "proxy_bind_not_loopback"),
        (LOOPBACK_PROXIES, "fd00::5", "proxy_bind_not_loopback"),
        (LOOPBACK_PROXIES, "127.0.0.1", None),
        (LOOPBACK_PROXIES, "::1", None),
        (MIXED_PROXIES, "10.0.0.5", None),
    ],
)
def test_serve_rules_team_refusal_by_settings_and_host(
    team: dict[str, object] | None,
    host: str,
    reason: str | None,
    files: dict[str, str],
) -> None:
    """Each mode and address is refused for its reason, with a text and a hint."""
    refusal = team_refusal(settings(team, files), host)

    if reason is None:
        assert refusal is None
    else:
        assert refusal is not None
        assert refusal.reason == reason
        assert refusal.text
        assert refusal.hint


def test_serve_rules_unusable_tls_files_are_named_with_the_cause(
    files: dict[str, str],
) -> None:
    """The refusal names both files and the cause; an encrypted key asks nothing."""
    encrypted = {"tls_cert": "{cert}", "tls_key": "{encrypted_key}"}
    mismatched = {"tls_cert": "{cert}", "tls_key": "{other_key}"}

    refused = team_refusal(settings(encrypted, files), "0.0.0.0")
    mismatch = team_refusal(settings(mismatched, files), "0.0.0.0")

    assert refused is not None and mismatch is not None
    assert files["cert"] in refused.text and files["encrypted_key"] in refused.text
    assert message("serve.tls_key_encrypted") in refused.text
    assert "KEY_VALUES_MISMATCH" in mismatch.text
