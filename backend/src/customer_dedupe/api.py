import csv
import io
import json
from collections.abc import Iterator
from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from customer_dedupe import storage, synth
from customer_dedupe.domain import Cluster, GoldenField
from customer_dedupe.engine import run
from customer_dedupe.evaluate import evaluate
from customer_dedupe.io import merge_plan_rows, read_contacts


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DEDUPE_")

    database_url: str = "sqlite:///./dedupe.db"
    max_upload_mb: int = 20
    max_records: int = 100_000
    cors_origins: list[str] = ["http://localhost:5173"]


class JobOut(BaseModel):
    id: str
    dataset_id: str
    dataset_name: str
    records: int
    created_at: datetime
    decisions_applied: int
    stats: dict[str, Any]
    evaluation: dict[str, Any] | None


class ClusterOut(BaseModel):
    id: str
    size: int
    golden: dict[str, Any]
    min_link_score: float | None
    members: list[dict[str, Any]]


class ReviewOut(BaseModel):
    id: int
    score: float
    priority: str
    reason: str
    evidence: list[dict[str, Any]]
    a: dict[str, Any]
    b: dict[str, Any]
    decided: bool | None = None


class Page[T](BaseModel):
    total: int
    items: list[T]


class DecisionIn(BaseModel):
    a: str = Field(min_length=1, max_length=200)
    b: str = Field(min_length=1, max_length=200)
    same: bool


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = storage.make_engine(settings.database_url)
    make_session = storage.session_factory(engine)
    max_bytes = settings.max_upload_mb * 1024 * 1024

    app = FastAPI(title="customer-dedupe", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    def get_session() -> Iterator[Session]:
        with make_session() as session:
            yield session

    SessionDep = Annotated[Session, Depends(get_session)]

    def job_out(session: Session, job: storage.Job) -> JobOut:
        ds = session.get(storage.Dataset, job.dataset_id)
        assert ds is not None
        return JobOut(
            id=job.id,
            dataset_id=ds.id,
            dataset_name=ds.name,
            records=ds.records,
            created_at=job.created_at,
            decisions_applied=job.decisions_applied,
            stats=job.stats,
            evaluation=job.evaluation,
        )

    def get_job(session: Session, job_id: str) -> storage.Job:
        job = session.get(storage.Job, job_id)
        if job is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
        return job

    def execute(session: Session, ds: storage.Dataset) -> JobOut:
        must, cannot = storage.decisions(session, ds.id)
        contacts = storage.load_contacts(session, ds.id)
        result = run(contacts, must_link=must, cannot_link=cannot)
        scores = None
        if ds.truth:
            s = evaluate(result, ds.truth)
            scores = {
                **asdict(s),
                "precision": s.precision,
                "recall": s.recall,
                "recall_after_review": s.recall_after_review,
            }
        job = storage.save_job(session, ds, result, len(must) + len(cannot), scores)
        return job_out(session, job)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/jobs", status_code=status.HTTP_201_CREATED)
    async def create_job(
        session: SessionDep,
        file: Annotated[UploadFile, File()],
        name: Annotated[str, Form(max_length=200)] = "Uploaded contacts",
        mapping: Annotated[str, Form(description="JSON: contact field -> CSV column")] = "{}",
    ) -> JobOut:
        data = await file.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "file too large")
        try:
            field_map = json.loads(mapping)
            if not isinstance(field_map, dict) or not all(
                isinstance(v, str) for v in field_map.values()
            ):
                raise ValueError("mapping must be a JSON object of strings")
            contacts = read_contacts(data.decode("utf-8-sig"), field_map)
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        if not contacts:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "no rows")
        if len(contacts) > settings.max_records:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE, f"more than {settings.max_records} records"
            )
        if len({c.id for c in contacts}) != len(contacts):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "ids must be unique")
        ds, _ = storage.get_or_create_dataset(session, name, contacts)
        return execute(session, ds)

    @app.post("/api/jobs/demo", status_code=status.HTTP_201_CREATED)
    def create_demo_job(session: SessionDep, seed: int = 11) -> JobOut:
        data = synth.generate(seed=seed)
        ds, _ = storage.get_or_create_dataset(
            session, f"Demo: CRM + ERP + shop contacts (seed {seed})", data.contacts, data.truth
        )
        return execute(session, ds)

    @app.post("/api/jobs/{job_id}/rerun", status_code=status.HTTP_201_CREATED)
    def rerun(job_id: str, session: SessionDep) -> JobOut:
        ds = session.get(storage.Dataset, get_job(session, job_id).dataset_id)
        assert ds is not None
        return execute(session, ds)

    @app.get("/api/jobs")
    def jobs(session: SessionDep) -> list[JobOut]:
        return [job_out(session, j) for j in storage.list_jobs(session)]

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str, session: SessionDep) -> JobOut:
        return job_out(session, get_job(session, job_id))

    @app.get("/api/jobs/{job_id}/clusters")
    def clusters(
        job_id: str,
        session: SessionDep,
        min_size: Annotated[int, Query(ge=1)] = 2,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> Page[ClusterOut]:
        job = get_job(session, job_id)
        query = select(storage.ClusterRow).where(
            storage.ClusterRow.job_id == job.id, storage.ClusterRow.size >= min_size
        )
        total, rows = storage.page(
            session, query, (storage.ClusterRow.size.desc(), storage.ClusterRow.id), limit, offset
        )
        ids = {m for r in rows for m in r.member_ids}
        people = storage.contacts_by_id(session, job.dataset_id, ids)
        return Page[ClusterOut](
            total=total,
            items=[
                ClusterOut(
                    id=r.id,
                    size=r.size,
                    golden=r.golden,
                    min_link_score=r.min_link_score,
                    members=[people[m] for m in r.member_ids if m in people],
                )
                for r in rows
            ],
        )

    @app.get("/api/jobs/{job_id}/review")
    def review(
        job_id: str,
        session: SessionDep,
        priority: Annotated[str | None, Query(pattern="^(high|low)$")] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> Page[ReviewOut]:
        job = get_job(session, job_id)
        query = select(storage.ReviewRow).where(storage.ReviewRow.job_id == job.id)
        if priority:
            query = query.where(storage.ReviewRow.priority == priority)
        total, rows = storage.page(
            session,
            query,
            (
                storage.ReviewRow.priority.asc(),
                storage.ReviewRow.score.desc(),
                storage.ReviewRow.id,
            ),
            limit,
            offset,
        )
        people = storage.contacts_by_id(
            session, job.dataset_id, {x for r in rows for x in (r.a, r.b)}
        )
        must, cannot = storage.decisions(session, job.dataset_id)
        decided = {**{p: True for p in must}, **{p: False for p in cannot}}
        return Page[ReviewOut](
            total=total,
            items=[
                ReviewOut(
                    id=r.id,
                    score=r.score,
                    priority=r.priority,
                    reason=r.reason,
                    evidence=r.evidence,
                    a=people.get(r.a, {"id": r.a}),
                    b=people.get(r.b, {"id": r.b}),
                    decided=decided.get((r.a, r.b)),
                )
                for r in rows
            ],
        )

    @app.post("/api/jobs/{job_id}/decisions", status_code=status.HTTP_204_NO_CONTENT)
    def decide(job_id: str, decision: DecisionIn, session: SessionDep) -> None:
        job = get_job(session, job_id)
        known = storage.contacts_by_id(session, job.dataset_id, {decision.a, decision.b})
        if len(known) != 2:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "record not in this dataset")
        storage.record_decision(session, job.dataset_id, decision.a, decision.b, decision.same)

    @app.get("/api/jobs/{job_id}/merge-plan.csv")
    def merge_plan(job_id: str) -> StreamingResponse:
        with make_session() as session:
            job = get_job(session, job_id)
            rows = session.scalars(
                select(storage.ClusterRow)
                .where(storage.ClusterRow.job_id == job.id)
                .order_by(storage.ClusterRow.size.desc(), storage.ClusterRow.id)
            ).all()
        clusters = [
            Cluster(
                id=r.id,
                member_ids=tuple(r.member_ids),
                golden={k: GoldenField(**v) for k, v in r.golden.items()},
                min_link_score=r.min_link_score,
            )
            for r in rows
        ]

        def body() -> Iterator[str]:
            buf = io.StringIO()
            writer = csv.writer(buf)
            for row in merge_plan_rows(clusters):
                writer.writerow(row)
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate()

        headers = {"Content-Disposition": f'attachment; filename="merge-plan-{job_id}.csv"'}
        return StreamingResponse(body(), media_type="text/csv", headers=headers)

    return app
