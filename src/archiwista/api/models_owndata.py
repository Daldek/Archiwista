"""API models of projects' own data (plan v0.2, decision 8; steps 7b and 9).

A file of a data folder is named by its project and ``file_id`` (16
characters of the SHA-256 of its path in the folder); ``ref`` is
``file:<project>:<path>`` and of a snapshot
``snapshot:<project>:<label>:<path>`` (decision 10). Absolute paths appear
only as copy paths (``CopyPath``), on this computer and as aliased elsewhere.
The request models refuse unknown parameters and members (``422``).
"""

from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from archiwista.api.models import CopyPath, Issue, Location
from archiwista.api.models_previews import PreviewInfo
from archiwista.config import AppSettings
from archiwista.index import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    OwnFileDetail,
    OwnFileObservation,
    OwnFilePage,
    OwnFileRow,
    OwnFolderRecord,
    OwnSnapshotRef,
    SnapshotRecord,
)
from archiwista.owndata.document import MAX_NOTE_CHARS, SNAPSHOTS_DIR
from archiwista.owndata.scan import OwnFolderCheck
from archiwista.owndata.snapshots import SnapshotPlan as PlannedSnapshot
from archiwista.refs import FileRef, SnapshotRef, format_ref, snapshot_files
from archiwista.services.problems import Problem


def copy_path(settings: AppSettings, path: Path) -> CopyPath:
    """Return a path on this computer and as every store's aliases write it."""
    aliases: list[str] = []
    for store in settings.stores:
        aliases += [
            alias for alias in store.foreign_paths(path) if alias not in aliases
        ]
    return CopyPath(local=str(path), aliases=aliases)


class OwnFilesQuery(BaseModel):
    """Filters and page of `GET /projects/{project}/files`."""

    model_config = ConfigDict(extra="forbid")

    q: str | None = Field(
        default=None,
        description="Words that must all occur in the path (ASCII case ignored).",
        examples=["kanalizacja"],
    )
    state: str | None = Field(
        default=None,
        description=(
            "Only files in this state (`ok`, `unrecognized`, `unreadable`,"
            " `missing`) or present files of this change (`unsnapshotted`,"
            " `unchanged`, `changed`)."
        ),
        examples=["changed"],
    )
    limit: int = Field(
        default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT, description="Page size."
    )
    cursor: str | None = Field(
        default=None,
        description="`next_cursor` of the previous page of the same filters.",
    )


class DataDirRequest(BaseModel):
    """What `PUT /projects/{project}/data-dir` reads."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [{"path": "/mnt/nas/raba/dane"}, {"path": None}]
        },
    )

    path: str | None = Field(
        description=(
            "Absolute folder on the server's computer; `null` brings back the"
            " default `<project directory>/dane`."
        )
    )


class SnapshotRequest(BaseModel):
    """What `POST /projects/{project}/files/{file_id}/snapshots` reads."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"note": "nowy kolektor deszczowy"}]},
    )

    note: str = Field(
        default="",
        max_length=MAX_NOTE_CHARS,
        description="The person's note kept in `migawka.json`.",
    )


class OwnFolder(BaseModel):
    """A project's data folder as its last scan found it."""

    path: CopyPath = Field(description="The folder (setting or `<project>/dane`).")
    source: Literal["default", "setting"]
    state: Literal["ok", "missing", "unreadable", "invalid"] = Field(
        description="`invalid`: refused by the rules (problem `own_folder_invalid`)."
    )
    files: int = Field(description="Files present.")
    size_bytes: int
    snapshots_bytes: int = Field(description="Bytes of the snapshots in `.wersje/`.")
    scanned_at: datetime | None = Field(
        description=(
            "When it was last scanned; `null`: not yet (its state is now's;"
            " `POST /projects/{project}/scan` reads it)."
        )
    )
    problems: list[Issue]

    @classmethod
    def of(
        cls,
        record: OwnFolderRecord,
        *,
        settings: AppSettings,
        problems: Sequence[Problem],
    ) -> Self:
        """Return the model of an indexed folder."""
        return cls(
            path=copy_path(settings, Path(record.path)),
            source=record.source,
            state=record.state,
            files=record.files,
            size_bytes=record.size_bytes,
            snapshots_bytes=record.snapshots_bytes,
            scanned_at=record.scanned_at,
            problems=[Issue.of(problem) for problem in problems],
        )

    @classmethod
    def checked(
        cls,
        check: OwnFolderCheck,
        *,
        settings: AppSettings,
        problems: Sequence[Problem],
    ) -> Self:
        """Return the model of a folder checked now, not scanned yet."""
        return cls(
            path=copy_path(settings, check.path),
            source=check.source,
            state=check.state,
            files=0,
            size_bytes=0,
            snapshots_bytes=0,
            scanned_at=None,
            problems=[Issue.of(problem) for problem in problems],
        )


class LastSnapshot(BaseModel):
    """The snapshot a file's change is measured against."""

    label: str
    created_at: datetime


class _OwnFileFields(BaseModel):
    """Fields of a file of a data folder, listed or on its card."""

    file_id: str = Field(description="16 hex characters; the file in URLs.")
    path: str = Field(description="Relative to the folder, `/` separated (NFC).")
    ref: str = Field(description="`file:<project>:<path>`.")
    kind: str
    format: str | None = Field(description="GDAL driver; null: not read by GDAL.")
    size_bytes: int
    modified_at: datetime
    state: Literal["ok", "unrecognized", "unreadable", "missing"]
    change: Literal["unsnapshotted", "unchanged", "changed"]
    last_snapshot: LastSnapshot | None
    location: Location

    @staticmethod
    def fields(project: str, row: OwnFileRow) -> dict[str, Any]:
        """Return the values of these fields for a file."""
        last = row.last_snapshot
        return {
            "file_id": row.file_id,
            "path": row.path,
            "ref": format_ref(FileRef(project, row.path)),
            "kind": row.kind,
            "format": row.driver,
            "size_bytes": row.size_bytes,
            "modified_at": row.modified_at,
            "state": row.state,
            "change": row.change,
            "last_snapshot": None
            if last is None
            else LastSnapshot(label=last.label, created_at=last.created_at),
            "location": Location(
                kind=row.location.kind,
                reason=row.location.reason,
                source=row.location.source,
            ),
        }


class OwnFileItem(_OwnFileFields):
    """A file of a data folder, with its change since its last snapshot."""

    snapshots: int = Field(description="Its snapshots in `.wersje/`.")
    outline: dict[str, Any] | None = Field(
        description=(
            "WGS84 polygon of its extent (GeoJSON) when `location.kind` is"
            " `footprint`, for the project's map; `null` otherwise."
        )
    )

    @classmethod
    def of(cls, project: str, row: OwnFileRow) -> Self:
        """Return the model of a listed file."""
        return cls(
            **cls.fields(project, row), snapshots=row.snapshots, outline=row.outline
        )


class OwnFileList(BaseModel):
    """Files of a data folder by path; `next_cursor` continues the list."""

    folder: OwnFolder
    items: list[OwnFileItem]
    next_cursor: str | None

    @classmethod
    def of(
        cls,
        page: OwnFilePage,
        *,
        settings: AppSettings,
        problems: Sequence[Problem],
    ) -> Self:
        """Return the model of a page of files."""
        project = page.folder.project
        return cls(
            folder=OwnFolder.of(page.folder, settings=settings, problems=problems),
            items=[OwnFileItem.of(project, row) for row in page.items],
            next_cursor=page.next_cursor,
        )


class Content(BaseModel):
    """Content identity (decision 8): how it was computed and its SHA-256."""

    method: Literal["bytes", "fileset", "sqlite"]
    sha256: str


class Observation(BaseModel):
    """An observed state of a file (its history, without content)."""

    observed_at: datetime
    size_bytes: int
    modified_at: datetime
    content_sha256: str | None
    feature_count: int | None

    @classmethod
    def of(cls, item: OwnFileObservation) -> Self:
        """Return the model of an observed state."""
        return cls(
            observed_at=item.observed_at,
            size_bytes=item.size_bytes,
            modified_at=item.modified_at,
            content_sha256=item.content_sha256,
            feature_count=item.feature_count,
        )


class SnapshotItem(BaseModel):
    """A snapshot of a file in `.wersje/` (`archiwista-snapshot/1`)."""

    label: str
    ref: str = Field(description="`snapshot:<project>:<label>:<path>`.")
    created_at: datetime | None
    author: dict[str, Any] | None
    note: str | None
    size_bytes: int
    content: Content | None
    feature_count: int | None
    extent: dict[str, Any] | None
    state: Literal["ok", "invalid", "modified"]
    members: list[str] = Field(
        description=(
            "Names of its files, the main file first: the `member` of"
            " `GET …/snapshots/{label}/file`."
        )
    )
    paths: CopyPath = Field(description="The snapshot directory.")

    @classmethod
    def of(
        cls, project: str, item: SnapshotRecord, *, folder: Path, settings: AppSettings
    ) -> Self:
        """Return the model of an indexed snapshot."""
        document = item.document or {}
        content = None
        if item.content_method is not None and item.content_sha256 is not None:
            content = Content.model_validate(
                {"method": item.content_method, "sha256": item.content_sha256}
            )
        directory = folder / SNAPSHOTS_DIR / item.path / item.label
        return cls(
            label=item.label,
            ref=format_ref(SnapshotRef(project, item.label, item.path)),
            created_at=item.created_at,
            author=_object(document.get("author")),
            note=_text(document.get("note")),
            size_bytes=item.size_bytes,
            content=content,
            feature_count=_count(document.get("feature_count")),
            extent=_object(document.get("extent")),
            state=item.state,
            members=[name for name, _ in snapshot_files(item)],
            paths=copy_path(settings, directory),
        )


class OwnFileCard(_OwnFileFields):
    """Everything known of an own file: what was read, history and snapshots."""

    layers: list[dict[str, Any]]
    raster: dict[str, Any] | None
    crs: str | None = Field(description="`EPSG:<code>` or WKT.")
    extent: dict[str, Any] | None = Field(
        description="`bbox` in `crs` and `wgs84` (GeoJSON polygon)."
    )
    content: Content | None
    history: list[Observation] = Field(description="Observed states, newest first.")
    snapshots: list[SnapshotItem] = Field(description="Newest first.")
    preview: PreviewInfo | None = Field(
        description=(
            "Its preview, as `GET …/files/{file_id}/preview` answers it (a file"
            " changed since its scan: `changed_since_scan`); `null` without"
            " render processes."
        )
    )
    paths: CopyPath = Field(description="The main file.")
    members: list[str] = Field(
        description=(
            "Names of the files of its set (a Shapefile, a MapInfo TAB), the main"
            " file first; its name alone for a single file. The `member` of"
            " `GET …/files/{file_id}/file`."
        )
    )
    problems: list[Issue]

    @classmethod
    def of(
        cls,
        project: str,
        detail: OwnFileDetail,
        *,
        settings: AppSettings,
        problems: Sequence[Problem],
        preview: PreviewInfo | None,
    ) -> Self:
        """Return the model of a file's card."""
        folder = Path(detail.folder.path)
        content = None
        if detail.content_method is not None and detail.content_sha256 is not None:
            content = Content.model_validate(
                {"method": detail.content_method, "sha256": detail.content_sha256}
            )
        extent = None
        if detail.native_bbox is not None:
            extent = {"bbox": list(detail.native_bbox), "wgs84": detail.wgs84}
        return cls(
            **cls.fields(project, detail.file),
            layers=[asdict(layer) for layer in detail.layers],
            raster=None if detail.raster is None else asdict(detail.raster),
            crs=detail.native_crs,
            extent=extent,
            content=content,
            history=[Observation.of(item) for item in detail.history],
            snapshots=[
                SnapshotItem.of(project, item, folder=folder, settings=settings)
                for item in detail.snapshots
            ],
            preview=preview,
            paths=copy_path(settings, folder / detail.disk_path),
            members=[PurePosixPath(member).name for member in detail.members],
            problems=[Issue.of(problem) for problem in problems],
        )


class PlanBlock(BaseModel):
    """Why a snapshot cannot be made now."""

    code: Literal[
        "folder_invalid", "read_only_folder", "insufficient_space", "file_missing"
    ] = Field(
        description=(
            "`folder_invalid` (the data folder breaks the rules),"
            " `read_only_folder` (no write access), `insufficient_space` (less"
            " than 1.1 times the file free) or `file_missing`."
        )
    )
    message: str = Field(description="Description.")


class PlanWarning(BaseModel):
    """What the person should know before a snapshot, not a refusal."""

    code: str = Field(
        description="`editing_detected`: open in an editor, committed changes only."
    )
    message: str = Field(description="Description.")


class SnapshotPlan(BaseModel):
    """What a snapshot of a file would do now; nothing is written."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "file": "sieci/kanalizacja.gpkg",
                    "size_bytes": 192512,
                    "destination": {
                        "local": "/mnt/nas/raba/dane/.wersje/sieci/kanalizacja.gpkg",
                        "aliases": [],
                    },
                    "copy_method": "sqlite_backup",
                    "content_method": "sqlite",
                    "unchanged_since": None,
                    "blocked": None,
                    "free_bytes": 52428800000,
                    "warnings": [],
                }
            ]
        }
    )

    file: str = Field(description="The working file, relative to the data folder.")
    size_bytes: int = Field(
        description="Bytes to copy: the file with its set, a SQLite `-wal` too."
    )
    destination: CopyPath = Field(
        description="Directory of the file's snapshots, `.wersje/<file>/`."
    )
    copy_method: Literal["sqlite_backup", "files"]
    content_method: Literal["sqlite", "fileset", "bytes"]
    unchanged_since: LastSnapshot | None = Field(
        description=(
            "The last snapshot, when the last scan found its content in the"
            " file: a new one would repeat it (`unchanged`)."
        )
    )
    blocked: PlanBlock | None = Field(
        description="Why `POST …/snapshots` would answer `409 snapshot_blocked`."
    )
    free_bytes: int | None = Field(
        description="Free bytes where the snapshot goes; `null`: out of reach."
    )
    warnings: list[PlanWarning]

    @classmethod
    def of(cls, plan: PlannedSnapshot, *, settings: AppSettings) -> Self:
        """Return the model of a planned snapshot."""
        since: OwnSnapshotRef | None = plan.unchanged_since
        return cls(
            file=plan.path,
            size_bytes=plan.size_bytes,
            destination=copy_path(settings, plan.destination),
            copy_method=plan.copy_method,
            content_method=plan.content_method,
            unchanged_since=None
            if since is None
            else LastSnapshot(label=since.label, created_at=since.created_at),
            blocked=None
            if plan.blocked is None
            else PlanBlock(code=plan.blocked.reason, message=plan.blocked.message),
            free_bytes=plan.free_bytes,
            warnings=[
                PlanWarning(code=item.code, message=item.message)
                for item in plan.warnings
            ],
        )


def _object(value: object) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
