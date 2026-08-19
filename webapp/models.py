"""Model danych.

Trzy obszary:
- `User` — kto się zalogował + token do Google Calendar (read-only).
- `Meeting` / `MeetingParticipant` / `Transcript` — lustro stanu Recall.ai
  wzbogacone o tytuł i zaproszonych z kalendarza.
- `Job` — kolejka zadań (fetch assetów, pipeline, sync). Patrz `webapp/jobs.py`.

Meeting.id == Recall bot_id. Jeden bot ma 0..n nagrań, ale w praktyce 0 albo 1,
więc trzymamy `recording_id` płasko i nie robimy osobnej tabeli.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class UtcDateTime(TypeDecorator):
    """Data i czas, które ZAWSZE wracają z bazy jako świadome strefy (UTC).

    SQLite nie przechowuje strefy — `DateTime(timezone=True)` zapisuje offset,
    ale przy odczycie oddaje naiwny `datetime`. Każde porównanie takiej wartości
    z `utcnow()` wywala `TypeError: can't compare offset-naive and offset-aware`.
    Trafiało to m.in. w widok spotkania z wygasłymi mediami i w dopasowanie
    wydarzeń kalendarza. Normalizujemy w jednym miejscu, zamiast łatać
    porównania po całym kodzie.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Optional[dt.datetime], dialect):  # noqa: ANN001
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc)

    def process_result_value(self, value: Optional[dt.datetime], dialect):  # noqa: ANN001
        if value is None:
            return None
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    google_sub: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(200))
    picture: Mapped[Optional[str]] = mapped_column(String(500))
    domain: Mapped[Optional[str]] = mapped_column(String(200), index=True)

    # Google Calendar (read-only). Refresh token dostajemy tylko przy
    # access_type=offline + prompt=consent, więc nie nadpisujemy go pustym.
    google_refresh_token: Mapped[Optional[str]] = mapped_column(Text)
    google_access_token: Mapped[Optional[str]] = mapped_column(Text)
    google_token_expires_at: Mapped[Optional[dt.datetime]] = mapped_column(UtcDateTime)
    calendar_scope_granted: Mapped[bool] = mapped_column(Boolean, default=False)
    calendar_synced_at: Mapped[Optional[dt.datetime]] = mapped_column(UtcDateTime)

    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_login_at: Mapped[Optional[dt.datetime]] = mapped_column(UtcDateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


# --------------------------------------------------------------------------
# Spotkania
# --------------------------------------------------------------------------

# Kanoniczne grupy statusów do filtrowania w UI. Recall ma kilkanaście kodów;
# użytkownika interesuje głównie: czeka / trwa / gotowe / nie wyszło.
STATUS_GROUPS: dict[str, str] = {
    "scheduled": "Scheduled",
    "joining": "Joining",
    "recording": "Recording",
    "done": "Finished",
    "failed": "Failed",
    "expired": "Media expired",
}

_RAW_TO_GROUP = {
    "ready": "scheduled",
    "scheduled": "scheduled",
    "joining_call": "joining",
    "in_waiting_room": "joining",
    "participant_in_waiting_room": "joining",
    "in_call_not_recording": "joining",
    "recording_permission_allowed": "recording",
    "in_call_recording": "recording",
    "recording_paused": "recording",
    "call_ended": "done",
    "done": "done",
    "analysis_done": "done",
    "recording_done": "done",
    "media_expired": "expired",
    "fatal": "failed",
    "recording_permission_denied": "failed",
    "call_join_failed": "failed",
}


def status_group(raw_code: Optional[str]) -> str:
    return _RAW_TO_GROUP.get((raw_code or "").lower(), "failed" if raw_code else "scheduled")


# Stan lokalnych assetów i transkryptu — sterują tym, co można kliknąć w UI.
ASSET_STATES = ("none", "queued", "fetching", "ready", "expired", "failed")
TRANSCRIPT_STATES = ("none", "queued", "running", "ready", "failed")


class Meeting(Base):
    __tablename__ = "meetings"

    # Recall bot_id.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    platform: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    meeting_native_id: Mapped[Optional[str]] = mapped_column(String(120), index=True)
    meeting_url: Mapped[Optional[str]] = mapped_column(String(500))

    title: Mapped[Optional[str]] = mapped_column(String(500), index=True)
    title_source: Mapped[Optional[str]] = mapped_column(String(20))  # calendar / manual / fallback

    join_at: Mapped[Optional[dt.datetime]] = mapped_column(UtcDateTime, index=True)
    started_at: Mapped[Optional[dt.datetime]] = mapped_column(UtcDateTime, index=True)
    completed_at: Mapped[Optional[dt.datetime]] = mapped_column(UtcDateTime)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float)

    status_code: Mapped[Optional[str]] = mapped_column(String(60), index=True)
    status_sub_code: Mapped[Optional[str]] = mapped_column(String(60))
    status_group: Mapped[str] = mapped_column(String(20), default="scheduled", index=True)
    status_updated_at: Mapped[Optional[dt.datetime]] = mapped_column(UtcDateTime)

    recording_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    media_expires_at: Mapped[Optional[dt.datetime]] = mapped_column(UtcDateTime, index=True)
    has_audio_mixed: Mapped[bool] = mapped_column(Boolean, default=False)
    has_audio_separate: Mapped[bool] = mapped_column(Boolean, default=False)

    asset_state: Mapped[str] = mapped_column(String(20), default="none", index=True)
    asset_dir: Mapped[Optional[str]] = mapped_column(String(1000))
    asset_error: Mapped[Optional[str]] = mapped_column(Text)
    transcript_state: Mapped[str] = mapped_column(String(20), default="none", index=True)
    transcript_error: Mapped[Optional[str]] = mapped_column(Text)

    # Denormalizacja pod wyszukiwarkę: "wiktor jarka|beata patfield|..."
    search_blob: Mapped[Optional[str]] = mapped_column(Text)

    calendar_event_id: Mapped[Optional[str]] = mapped_column(String(300), index=True)
    calendar_organizer: Mapped[Optional[str]] = mapped_column(String(320))
    calendar_html_link: Mapped[Optional[str]] = mapped_column(String(700))

    raw_bot: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    synced_at: Mapped[Optional[dt.datetime]] = mapped_column(UtcDateTime)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow)

    participants: Mapped[list["MeetingParticipant"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", lazy="selectin",
    )
    transcripts: Mapped[list["Transcript"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", lazy="selectin",
        order_by="Transcript.created_at.desc()",
    )

    @property
    def latest_transcript(self) -> Optional["Transcript"]:
        return self.transcripts[0] if self.transcripts else None

    @property
    def occurred_at(self) -> Optional[dt.datetime]:
        return self.started_at or self.join_at

    @property
    def human_participants(self) -> list["MeetingParticipant"]:
        """Ludzie bez duplikatów — ta sama osoba bywa i w Recall, i w kalendarzu.

        Wygrywa wpis z Recall (był realnie w callu), a osoby obecne idą przed
        samymi zaproszonymi.
        """
        best: dict[str, MeetingParticipant] = {}
        for p in self.participants:
            if p.is_bot:
                continue
            current = best.get(p.key)
            if current is None or (current.source != "recall" and p.source == "recall"):
                best[p.key] = p
        return sorted(best.values(), key=lambda p: (p.source != "recall", not p.is_host, p.display))


Index("ix_meetings_started_status", Meeting.started_at, Meeting.status_group)


# Nazwy botów-notetakerów, które nie są ludźmi — nie chcemy ich w filtrach.
_BOT_NAME_MARKERS = (
    "notetaker", "note taker", "fireflies", "otter", "fathom", "read.ai",
    "recall.ai", "avoma", "gong", "chorus", "tl;dv", "tldv", "sembly",
    "zoom ai companion", "meeting recorder", "transcription bot",
)


def looks_like_bot(name: Optional[str], email: Optional[str] = None) -> bool:
    """Czy to notetaker, a nie człowiek.

    Kalendarz często podaje sam adres bez nazwy (`fred@fireflies.ai`), więc
    sprawdzanie samej nazwy przepuszczało boty do listy uczestników.
    """
    haystack = f"{name or ''} {email or ''}".lower()
    return any(m in haystack for m in _BOT_NAME_MARKERS)


class MeetingParticipant(Base):
    """Uczestnik spotkania.

    Źródła: `recall` (realnie był w callu, z participants.json / audio_separate)
    oraz `calendar` (zaproszony w Google Calendar, może nie przyszedł).
    Trzymamy oba, bo filtrowanie "spotkania z X" powinno łapać też te, gdzie
    X był zaproszony, a lista mówców bierze się tylko z `recall`.
    """

    __tablename__ = "meeting_participants"
    __table_args__ = (
        UniqueConstraint("meeting_id", "source", "key", name="uq_participant"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(20), default="recall")  # recall | calendar
    key: Mapped[str] = mapped_column(String(400), index=True)  # znormalizowany email lub nazwa
    name: Mapped[Optional[str]] = mapped_column(String(300))
    email: Mapped[Optional[str]] = mapped_column(String(320), index=True)
    # Skąd wziął się adres: `recall` (ich fuzzy matching), `calendar`
    # (wprost z zaproszenia), `matched` (nasze dopasowanie nazwy do adresu).
    # Trzymamy to, żeby dało się odróżnić pewne od wywnioskowanego i żeby
    # człowiek mógł poprawić błąd, gdyby się trafił.
    email_source: Mapped[Optional[str]] = mapped_column(String(12))
    match_score: Mapped[Optional[float]] = mapped_column(Float)
    is_host: Mapped[bool] = mapped_column(Boolean, default=False)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    response_status: Mapped[Optional[str]] = mapped_column(String(30))
    speaking_seconds: Mapped[Optional[float]] = mapped_column(Float)

    meeting: Mapped[Meeting] = relationship(back_populates="participants")

    @property
    def display(self) -> str:
        return self.name or self.email or self.key


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), index=True)
    recording_id: Mapped[Optional[str]] = mapped_column(String(64))

    engine: Mapped[str] = mapped_column(String(60), default="pipeline-recall")
    language: Mapped[Optional[str]] = mapped_column(String(10))
    text_path: Mapped[str] = mapped_column(String(1000))
    raw_path: Mapped[Optional[str]] = mapped_column(String(1000))

    speakers: Mapped[Optional[list[Any]]] = mapped_column(JSON)
    utterance_count: Mapped[Optional[int]] = mapped_column(Integer)
    word_count: Mapped[Optional[int]] = mapped_column(Integer)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float)
    stats: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)

    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)

    meeting: Mapped[Meeting] = relationship(back_populates="transcripts")


# --------------------------------------------------------------------------
# Kolejka zadań
# --------------------------------------------------------------------------

JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_DONE = "done"
JOB_FAILED = "failed"
JOB_CANCELED = "canceled"

ACTIVE_JOB_STATES = (JOB_QUEUED, JOB_RUNNING)


class Job(Base):
    """Jedno zadanie w kolejce.

    `dedupe_key` + partial-unique-index nie są przenośne między SQLite a
    Postgresem, więc deduplikację robimy w `jobs.enqueue()` transakcyjnie
    (sprawdź czy jest aktywny job o tym kluczu → jak tak, zwróć istniejący).
    """

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(20), default=JOB_QUEUED, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)  # mniej = pilniej

    meeting_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), index=True,
    )
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(300), index=True)
    args: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)

    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)

    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    step: Mapped[Optional[str]] = mapped_column(String(200))
    log: Mapped[Optional[str]] = mapped_column(Text)
    result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    error: Mapped[Optional[str]] = mapped_column(Text)

    scheduled_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)
    started_at: Mapped[Optional[dt.datetime]] = mapped_column(UtcDateTime)
    finished_at: Mapped[Optional[dt.datetime]] = mapped_column(UtcDateTime)
    heartbeat_at: Mapped[Optional[dt.datetime]] = mapped_column(UtcDateTime, index=True)
    worker_id: Mapped[Optional[str]] = mapped_column(String(80))
    created_by: Mapped[Optional[str]] = mapped_column(String(320))

    meeting: Mapped[Optional[Meeting]] = relationship()


Index("ix_jobs_claim", Job.status, Job.priority, Job.scheduled_at)
