"""JSON Lines between the job supervisor and its workers (SPEC 5.6)."""

from pathlib import Path

import pytest

from archiwista.config import AppSettings, StoreConfig
from archiwista.jobs.protocol import (
    JobKind,
    JobSpec,
    JsonObject,
    ProtocolError,
    WorkerMessage,
    decode_message,
    decode_spec,
    encode_message,
    encode_spec,
)


@pytest.mark.parametrize(
    "message",
    [
        WorkerMessage("progress", {"current": 0, "total": 3, "segment": None}),
        WorkerMessage(
            "notice", {"level": "warning", "code": "x", "message": "Zażółć\ngęślą"}
        ),
        WorkerMessage("result", {"entries": 3, "segments": [{"segment": "nmt/a"}]}),
        WorkerMessage(
            "error", {"code": "store_unavailable", "detail": "brak", "exception": "E"}
        ),
    ],
)
def test_message_is_one_line_read_back_equal(message: WorkerMessage) -> None:
    """Each message type travels as one line, Polish text and line ends included."""
    line = encode_message(message)

    assert "\n" not in line
    assert decode_message(line + "\n") == message


@pytest.mark.parametrize(
    "line",
    [
        "Traceback (most recent call last):",
        "[1, 2]",
        '{"type": "debug", "data": {}}',
        '{"type": "result", "data": [1]}',
        '{"type": "progress", "data": {"current": "1", "total": 2}}',
        '{"type": "progress", "data": {"current": true, "total": 2}}',
        '{"type": "notice", "data": {"level": "debug", "code": "c", "message": "m"}}',
        '{"type": "error", "data": {"code": "c"}}',
    ],
)
def test_decode_message_rejects_what_is_not_a_message(line: str) -> None:
    """Stray output and messages without their members are protocol errors."""
    with pytest.raises(ProtocolError):
        decode_message(line)


@pytest.mark.parametrize(
    ("kind", "store", "params"),
    [
        ("link_check", "zespol", {"slot": "nmt/a/N-34/x.asc"}),
        (
            "preview",
            None,
            {
                "refs": ["version:zespol:nmt/a/N-34/2026-10-01_x.asc"],
                "contents": ["0f" * 32],
                "force": False,
            },
        ),
    ],
)
def test_job_spec_keeps_settings_and_paths(
    kind: JobKind, store: str | None, params: JsonObject
) -> None:
    """A job, also one on no store, reaches its worker with paths and settings."""
    config = StoreConfig(
        id="zespol",
        name="Zespół",
        kartograf=Path("/mnt/nas/kartograf/data"),
        kind="share",
        path_aliases={"/mnt/nas/kartograf": "Z:\\kartograf"},
    )
    data = Path("/home/u/.local/share/archiwista")
    spec = JobSpec(
        job_id="0123456789abcdef",
        kind=kind,
        store=store,
        params=params,
        actor="agent-7",
        actor_kind="agent",
        session="Przeglądarka 1",
        index_path=data / "index.sqlite",
        cache_dir=data / "cache",
        previews_dir=data / "previews",
        work_dir=data / "work",
        settings=AppSettings(stores=(config,), offline=True, scan_threads=3),
    )

    assert decode_spec(encode_spec(spec)) == spec


@pytest.mark.parametrize(
    "line",
    [
        '{"protocol": 2, "job": {"id": "a", "kind": "scan", "store": "s",'
        ' "params": {}, "actor": "local"}, "index_path": "/i", "cache_dir": "/c",'
        ' "previews_dir": "/p", "work_dir": "/w", "settings": {}}',
        '{"protocol": 3, "job": {"id": "a", "kind": "download"}}',
        '{"protocol": 3, "job": {"id": "a", "kind": "scan", "store": "s",'
        ' "params": {}, "actor": "local", "actor_kind": "robot", "session": null},'
        ' "index_path": "/i", "cache_dir": "/c", "previews_dir": "/p",'
        ' "work_dir": "/w", "settings": {}}',
        '{"protocol": 3, "job": {"id": "a", "kind": "scan", "store": "s",'
        ' "params": {}, "actor": "local", "actor_kind": "local_owner",'
        ' "session": null}, "index_path": "/i", "cache_dir": "/c",'
        ' "previews_dir": "/p", "work_dir": "/w", "settings": {"port": 1}}',
    ],
)
def test_decode_spec_rejects_unknown_jobs(line: str) -> None:
    """Another protocol version, an unknown kind or actor, bad settings: refused."""
    with pytest.raises(ProtocolError):
        decode_spec(line)
