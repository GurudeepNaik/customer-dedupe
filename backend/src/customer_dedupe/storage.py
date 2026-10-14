"""Persistence. A dataset is stored once (fingerprinted); every run against it is a job; human
review decisions belong to the dataset, so they carry forward into every later job."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    func,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from customer_dedupe.domain import Contact, Result


class Base(DeclarativeBase):
    pass


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    records: Mapped[int] = mapped_column(Integer)
    # Ground truth is only present for synthetic demo data.
    truth: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ContactRow(Base):
    __tablename__ = "contacts"
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), primary_key=True)
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decisions_applied: Mapped[int] = mapped_column(Integer)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON)
    evaluation: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class ClusterRow(Base):
    __tablename__ = "clusters"
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), primary_key=True)
    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    size: Mapped[int] = mapped_column(Integer, index=True)
    member_ids: Mapped[list[str]] = mapped_column(JSON)
    golden: Mapped[dict[str, Any]] = mapped_column(JSON)
    min_link_score: Mapped[float | None] = mapped_column(Float)


class ReviewRow(Base):
    __tablename__ = "review_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    a: Mapped[str] = mapped_column(String(200))
    b: Mapped[str] = mapped_column(String(200))
    score: Mapped[float] = mapped_column(Float)
    priority: Mapped[str] = mapped_column(String(8))
    reason: Mapped[str] = mapped_column(String(300))
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON)


class DecisionRow(Base):
    __tablename__ = "decisions"
    __table_args__ = (UniqueConstraint("dataset_id", "a", "b"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    a: Mapped[str] = mapped_column(String(200))
    b: Mapped[str] = mapped_column(String(200))
    same: Mapped[bool] = mapped_column(Boolean)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def make_engine(url: str) -> Engine:
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    return engine


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def _contact_json(c: Contact) -> dict[str, Any]:
    data = asdict(c)
    data.pop("raw", None)
    data["updated_at"] = c.updated_at.isoformat() if c.updated_at else None
    return data


def _contact_from(data: dict[str, Any]) -> Contact:
    ts = data.get("updated_at")
    return Contact(**{**data, "updated_at": datetime.fromisoformat(ts) if ts else None})


def fingerprint(contacts: Sequence[Contact]) -> str:
    h = hashlib.sha256()
    for c in sorted(contacts, key=lambda c: c.id):
        h.update(json.dumps(_contact_json(c), sort_keys=True).encode())
    return h.hexdigest()


def get_or_create_dataset(
    session: Session, name: str, contacts: Sequence[Contact], truth: dict[str, str] | None = None
) -> tuple[Dataset, bool]:
    fp = fingerprint(contacts)
    if existing := session.scalar(select(Dataset).where(Dataset.fingerprint == fp)):
        return existing, False
    ds = Dataset(
        id=str(uuid.uuid4()),
        fingerprint=fp,
        name=name,
        records=len(contacts),
        truth=truth,
        created_at=datetime.now(UTC),
    )
    session.add(ds)
    session.flush()
    session.add_all(ContactRow(dataset_id=ds.id, id=c.id, data=_contact_json(c)) for c in contacts)
    session.flush()
    return ds, True


def load_contacts(session: Session, dataset_id: str) -> list[Contact]:
    rows = session.scalars(select(ContactRow).where(ContactRow.dataset_id == dataset_id))
    return [_contact_from(r.data) for r in rows]


def contacts_by_id(session: Session, dataset_id: str, ids: set[str]) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    rows = session.scalars(
        select(ContactRow).where(ContactRow.dataset_id == dataset_id, ContactRow.id.in_(ids))
    )
    return {r.id: r.data for r in rows}


def decisions(
    session: Session, dataset_id: str
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    rows = session.scalars(select(DecisionRow).where(DecisionRow.dataset_id == dataset_id)).all()
    must = [(r.a, r.b) for r in rows if r.same]
    cannot = [(r.a, r.b) for r in rows if not r.same]
    return must, cannot


def record_decision(session: Session, dataset_id: str, a: str, b: str, same: bool) -> None:
    a, b = sorted((a, b))
    row = session.scalar(
        select(DecisionRow).where(
            DecisionRow.dataset_id == dataset_id, DecisionRow.a == a, DecisionRow.b == b
        )
    )
    if row is None:
        row = DecisionRow(dataset_id=dataset_id, a=a, b=b, same=same, decided_at=datetime.now(UTC))
        session.add(row)
    else:
        row.same, row.decided_at = same, datetime.now(UTC)
    session.commit()


def save_job(
    session: Session,
    dataset: Dataset,
    result: Result,
    decisions_applied: int,
    evaluation: dict[str, Any] | None,
) -> Job:
    job = Job(
        id=str(uuid.uuid4()),
        dataset_id=dataset.id,
        created_at=datetime.now(UTC),
        decisions_applied=decisions_applied,
        stats=asdict(result.stats),
        evaluation=evaluation,
    )
    session.add(job)
    session.flush()
    session.add_all(
        ClusterRow(
            job_id=job.id,
            id=c.id,
            size=len(c.member_ids),
            member_ids=list(c.member_ids),
            golden={k: asdict(v) for k, v in c.golden.items()},
            min_link_score=c.min_link_score,
        )
        for c in result.clusters
    )
    session.add_all(
        ReviewRow(
            job_id=job.id,
            a=r.pair.a,
            b=r.pair.b,
            score=r.pair.score,
            priority=r.priority.value,
            reason=r.reason,
            evidence=[asdict(e) for e in r.pair.evidence],
        )
        for r in result.review
    )
    session.commit()
    return job


def list_jobs(session: Session, limit: int = 50) -> Sequence[Job]:
    return session.scalars(select(Job).order_by(Job.created_at.desc()).limit(limit)).all()


def page(
    session: Session, query: Any, order: Any, limit: int, offset: int
) -> tuple[int, Sequence[Any]]:
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(query.order_by(*order).limit(limit).offset(offset)).all()
    return total, rows
