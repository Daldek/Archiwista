"""API models of projects' own data (plan v0.2, decision 8; steps 7b and 9).

A file of a data folder is named by its project and ``file_id`` (16
characters of the SHA-256 of its path in the folder); ``ref`` is
``file:<project>:<path>`` and of a snapshot
``snapshot:<project>:<label>:<path>`` (decision 10). Absolute paths appear
only as copy paths (``CopyPath``), on this computer and as aliased elsewhere.
"""

from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, Field

from archiwista.api.models import CopyPath, Issue, Location
from archiwista.config import AppSettings
from archiwista.index import (
    OwnFileDetail,
    OwnFileObservation,
    OwnFilePage,
    OwnFileRow,
    OwnFolderRecord,
    SnapshotRecord,
)
from archiwista.owndata.document import SNAPSHOTS_DIR
from archiwista.services.problems import Problem


def file_ref(project: str, path: str) -> str:
    """Return the ``ref`` of a working file (decision 10)."""
    return f"file:{project}:{path}"


def snapshot_ref(project: str, label: str, path: str) -> str:
    """Return the ``ref`` of a snapshot (decision 10)."""
    return f"snapshot:{project}:{label}:{path}"


def copy_path(settings: AppSettings, path: Path) -> CopyPath:
    """Return a path on this computer and as every store's aliases write it."""
    aliases: list[str] = []
    for store in settings.stores:
        aliases += [
            alias for alias in store.foreign_paths(path) if alias not in aliases
        ]
    return CopyPath(local=str(path), aliases=aliases)


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
    scanned_at: datetime
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
        return dict(
            file_id=row.file_id,
            path=row.path,
            ref=file_ref(project, row.path),
            kind=row.kind,
            format=row.driver,
            size_bytes=row.size_bytes,
            modified_at=row.modified_at,
            state=row.state,
            change=row.change,
            last_snapshot=None
            if last is None
            else LastSnapshot(label=last.label, created_at=last.created_at),
            location=Location(
                kind=row.location.kind,
                reason=row.location.reason,
                source=row.location.source,
            ),
        )


class OwnFileItem(_OwnFileFields):
    """A file of a data folder, with its change since its last snapshot."""

    snapshots: int = Field(description="Its snapshots in `.wersje/`.")

    @classmethod
    def of(cls, project: str, row: OwnFileRow) -> Self:
        """Return the model of a listed file."""
        return cls(**cls.fields(project, row), snapshots=row.snapshots)


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
            ref=snapshot_ref(project, item.label, item.path),
            created_at=item.created_at,
            author=_object(document.get("author")),
            note=_text(document.get("note")),
            size_bytes=item.size_bytes,
            content=content,
            feature_count=_count(document.get("feature_count")),
            extent=_object(document.get("extent")),
            state=item.state,
            paths=copy_path(settings, directory),
        )


class OwnFileCard(_OwnFileFields):
    """Everything known of an own file: what was read, history and snapshots.

    Its preview (`preview`) joins in step 9 with the routes of previews.
    """

    layers: list[dict[str, Any]]
    raster: dict[str, Any] | None
    crs: str | None = Field(description="`EPSG:<code>` or WKT.")
    extent: dict[str, Any] | None = Field(
        description="`bbox` in `crs` and `wgs84` (GeoJSON polygon)."
    )
    content: Content | None
    history: list[Observation] = Field(description="Observed states, newest first.")
    snapshots: list[SnapshotItem] = Field(description="Newest first.")
    paths: CopyPath = Field(description="The main file.")
    problems: list[Issue]

    @classmethod
    def of(
        cls,
        project: str,
        detail: OwnFileDetail,
        *,
        settings: AppSettings,
        problems: Sequence[Problem],
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
            paths=copy_path(settings, folder / detail.disk_path),
            problems=[Issue.of(problem) for problem in problems],
        )


def _object(value: object) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
