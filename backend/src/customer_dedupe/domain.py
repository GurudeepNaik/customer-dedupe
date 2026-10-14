"""Core types. A Contact is what a source system gave us; a Profile is its normalised view."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

FIELDS = (
    "first_name",
    "last_name",
    "email",
    "phone",
    "company",
    "street",
    "city",
    "postal_code",
)


@dataclass(frozen=True, slots=True)
class Contact:
    id: str
    source: str = ""
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    company: str = ""
    street: str = ""
    city: str = ""
    region: str = ""
    postal_code: str = ""
    country: str = ""
    updated_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)


@dataclass(frozen=True, slots=True)
class Profile:
    """Normalised, comparison-ready view of a Contact. Empty string means 'not known'."""

    contact: Contact
    first: str
    first_canonical: str  # nickname resolved: bob -> robert
    last: str
    email: str
    phone: str
    company: str
    street: str
    city: str
    postal: str

    @property
    def id(self) -> str:
        return self.contact.id


class Agreement(StrEnum):
    SAME = "same"
    SIMILAR = "similar"
    DIFFERENT = "different"
    # Missing data is not contrary data.
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Evidence:
    field: str
    agreement: Agreement
    similarity: float
    weight: float
    left: str
    right: str


class Decision(StrEnum):
    MERGE = "merge"
    REVIEW = "review"
    DISTINCT = "distinct"


@dataclass(frozen=True, slots=True)
class PairScore:
    a: str
    b: str
    score: float
    decision: Decision
    evidence: tuple[Evidence, ...]
    vetoes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GoldenField:
    value: str
    source_id: str
    rule: str


@dataclass(frozen=True, slots=True)
class Cluster:
    id: str
    member_ids: tuple[str, ...]
    golden: dict[str, GoldenField]
    min_link_score: float | None


class Priority(StrEnum):
    # Identity is corroborated by a shared email, phone or street; a rule held it back.
    HIGH = "high"
    # Only name and place agree. Genuinely ambiguous: often a namesake, sometimes a person
    # whose contact details all changed.
    LOW = "low"


@dataclass(frozen=True, slots=True)
class ReviewItem:
    pair: PairScore
    reason: str
    priority: Priority = Priority.HIGH


@dataclass(frozen=True, slots=True)
class Stats:
    records: int
    candidate_pairs: int
    oversized_blocks: int
    merges: int
    reviews: int
    clusters: int
    blocked_by_constraint: int


@dataclass(frozen=True, slots=True)
class Result:
    clusters: tuple[Cluster, ...]
    review: tuple[ReviewItem, ...]
    pairs: tuple[PairScore, ...]
    stats: Stats
