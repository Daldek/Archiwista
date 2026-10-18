"""JSON Lines between the job supervisor and its workers (SPEC 5.6)."""

from pathlib import Path

import pytest

from archiwista.config import AppSettings, StoreConfig
from archiwista.jobs.protocol import (
    JobSpec,
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


def test_job_spec_keeps_settings_and_paths() -> None:
    """A job reaches its worker with the settings in effect, aliases included."""
    store = StoreConfig(
        id="zespol",
        name="Zespół",
        kartograf=Path("/mnt/nas/kartograf/data"),
        kind="share",
        path_aliases={"/mnt/nas/kartograf": "Z:\\kartograf"},
    )
    spec = JobSpec(
        job_id="0123456789abcdef",
        kind="link_check",
        store="zespol",
        params={"slot": "nmt/a/N-34/x.asc"},
        actor="agent-7",
        index_path=Path("/home/u/.local/share/archiwista/index.sqlite"),
        cache_dir=Path("/home/u/.local/share/archiwista/cache"),
        settings=AppSettings(stores=(store,), offline=True, scan_threads=3),
    )

    assert decode_spec(encode_spec(spec)) == spec


@pytest.mark.parametrize(
    "line",
    [
        '{"protocol": 2, "job": {}}',
        '{"protocol": 1, "job": {"id": "a", "kind": "download"}}',
        '{"protocol": 1, "job": {"id": "a", "kind": "scan", "store": "s",'
        ' "params": {}, "actor": "local"}, "index_path": "/i", "cache_dir": "/c",'
        ' "settings": {"port": 1}}',
    ],
)
def test_decode_spec_rejects_unknown_jobs(line: str) -> None:
    """Another protocol version, an unknown kind or invalid settings are refused."""
    with pytest.raises(ProtocolError):
        decode_spec(line)
