"""API models of the feedback reports ("Zgłoś uwagę"; Hydrograf's mechanism).

``NewFeedback`` is what a session sends to ``POST /feedback``, with
Hydrograf's limits: the description is 1 to 5,000 characters (blank is
refused), the contact at most 200, the page's address at most 500 and the
diagnostics at most 100,000 characters as compact JSON. ``FeedbackItem`` is a
report as an administrator reads it (``GET /admin/feedback``, a page of
``FeedbackList`` with the counts of all reports) and as ``PATCH
/admin/feedback/{id}`` answers it. The request models refuse unknown fields
and parameters.
"""

import json
from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

from archiwista.messages import message
from archiwista.services.feedback import (
    CONTACT_MAX_LENGTH,
    DEFAULT_FEEDBACK_LIMIT,
    DIAGNOSTICS_MAX_LENGTH,
    MAX_FEEDBACK_LIMIT,
    MESSAGE_MAX_LENGTH,
    PAGE_URL_MAX_LENGTH,
)
from archiwista.state import FeedbackPage, FeedbackRecord

_DIAGNOSTICS_EXAMPLE: dict[str, Any] = {
    "events": [
        {
            "t": "2026-11-03T09:14:02.120Z",
            "type": "api_call",
            "data": {
                "method": "GET",
                "endpoint": "/api/v1/slots?q=N-34-130-D&limit=50",
                "status": 200,
                "duration_ms": 41,
            },
        },
        {
            "t": "2026-11-03T09:14:05.874Z",
            "type": "js_error",
            "data": {"message": "TypeError: x is undefined", "source": None},
        },
    ],
    "view": {"view": "catalog", "params": {"q": "N-34-130-D"}},
    "env": {
        "userAgent": "Mozilla/5.0 (X11; Linux x86_64; rv:144.0) Firefox/144.0",
        "language": "pl-PL",
        "viewport": {"width": 1440, "height": 900},
        "url": "http://127.0.0.1:8090/?view=catalog&q=N-34-130-D",
        "timestamp": "2026-11-03T09:14:11.002Z",
        "version": "0.4.0",
    },
}
_ITEM_EXAMPLE: dict[str, Any] = {
    "id": 12,
    "created_at": "2026-11-03T09:14:12Z",
    "user_id": "marek.lis",
    "message": "The catalog shows no sheets after a search by code.",
    "contact": "marek.lis@example.com",
    "page_url": "http://127.0.0.1:8090/?view=catalog&q=N-34-130-D",
    "user_agent": "Mozilla/5.0 (X11; Linux x86_64; rv:144.0) Firefox/144.0",
    "diagnostics": _DIAGNOSTICS_EXAMPLE,
    "is_read": False,
}


class NewFeedback(BaseModel):
    """A report sent with "Zgłoś uwagę"."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "message": _ITEM_EXAMPLE["message"],
                    "contact": _ITEM_EXAMPLE["contact"],
                    "page_url": _ITEM_EXAMPLE["page_url"],
                    "diagnostics": _DIAGNOSTICS_EXAMPLE,
                }
            ]
        },
    )

    message: str = Field(
        min_length=1,
        max_length=MESSAGE_MAX_LENGTH,
        description="What happened or what could be better; blank is refused.",
    )
    contact: str | None = Field(
        default=None,
        max_length=CONTACT_MAX_LENGTH,
        description="A name or an e-mail address to answer; blank is none.",
    )
    page_url: str | None = Field(
        default=None,
        max_length=PAGE_URL_MAX_LENGTH,
        description="The address of the page the report was sent from.",
    )
    diagnostics: dict[str, Any] | None = Field(
        default=None,
        description=(
            "What the person chose to attach: the interface's recent events (API"
            " calls, script errors), the view and its parameters, the environment;"
            " at most 100,000 characters as compact JSON."
        ),
    )

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError(message("feedback.message_blank"))
        return stripped

    @field_validator("contact")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        stripped = None if value is None else value.strip()
        return stripped or None

    @field_validator("diagnostics")
    @classmethod
    def _within_limit(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        compact = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(compact) > DIAGNOSTICS_MAX_LENGTH:
            raise ValueError(
                message("feedback.diagnostics_too_large", limit=DIAGNOSTICS_MAX_LENGTH)
            )
        return value


class FeedbackCreated(BaseModel):
    """The number of the report just kept."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"id": 12, "status": "ok"}]}
    )

    id: int = Field(description="The report's number.")
    status: Literal["ok"] = Field(default="ok", description="Always `ok`.")


class FeedbackItem(BaseModel):
    """A report as an administrator reads it."""

    model_config = ConfigDict(json_schema_extra={"examples": [_ITEM_EXAMPLE]})

    id: int = Field(description="The report's number; a later one is greater.")
    created_at: datetime = Field(description="When it was sent (UTC).")
    user_id: str | None = Field(
        description=(
            "The account that sent it (an agent's: its person's); null for the"
            " owner of a local installation."
        )
    )
    message: str = Field(description="What the person wrote.")
    contact: str | None = Field(description="A name or an e-mail address.")
    page_url: str | None = Field(description="The page it was sent from.")
    user_agent: str | None = Field(
        description="The browser's `User-Agent`, cut to 500 characters."
    )
    diagnostics: dict[str, Any] | None = Field(
        description="The attached diagnostics; null when the person attached none."
    )
    is_read: bool = Field(description="Whether an administrator marked it read.")

    @classmethod
    def of(cls, record: FeedbackRecord) -> Self:
        """Return the model of a report."""
        return cls(
            id=record.id,
            created_at=record.created_at,
            user_id=record.user_id,
            message=record.message,
            contact=record.contact,
            page_url=record.page_url,
            user_agent=record.user_agent,
            diagnostics=record.diagnostics,
            is_read=record.is_read,
        )


class FeedbackList(BaseModel):
    """A page of the reports, newest first, with the counts of all of them."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"items": [_ITEM_EXAMPLE], "total": 31, "unread_count": 4}]
        }
    )

    items: list[FeedbackItem]
    total: int = Field(ge=0, description="How many reports there are, all pages.")
    unread_count: int = Field(ge=0, description="How many of them are unread.")

    @classmethod
    def of(cls, page: FeedbackPage) -> Self:
        """Return the model of a page of the reports."""
        return cls(
            items=[FeedbackItem.of(record) for record in page.items],
            total=page.total,
            unread_count=page.unread,
        )


class FeedbackListQuery(BaseModel):
    """The page of `GET /admin/feedback`, newest report first."""

    model_config = ConfigDict(extra="forbid")

    limit: int = Field(
        default=DEFAULT_FEEDBACK_LIMIT,
        ge=1,
        le=MAX_FEEDBACK_LIMIT,
        description="Page size.",
    )
    offset: int = Field(default=0, ge=0, description="How many newest to skip.")


class FeedbackChange(BaseModel):
    """Whether a report is read."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"is_read": True}]}
    )

    is_read: bool = Field(strict=True, description="`true`: read; `false`: unread.")
