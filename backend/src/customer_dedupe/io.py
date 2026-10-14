"""CSV in, merge plan out."""

from __future__ import annotations

import csv
import io
from collections import Counter
from collections.abc import Iterator, Mapping
from datetime import datetime

from customer_dedupe.domain import Cluster, Contact

CONTACT_FIELDS = (
    "id", "source", "first_name", "last_name", "email", "phone", "company",
    "street", "city", "region", "postal_code", "country", "updated_at",
)  # fmt: skip
GOLDEN_FIELDS = (
    "first_name", "last_name", "email", "phone", "company",
    "street", "city", "region", "postal_code", "country",
)  # fmt: skip


def read_contacts(text: str, mapping: Mapping[str, str] | None = None) -> list[Contact]:
    """mapping: contact field -> CSV column; unmapped fields use a column of the same name."""
    mapping = mapping or {}
    unknown = set(mapping) - set(CONTACT_FIELDS)
    if unknown:
        raise ValueError(f"unknown contact fields in mapping: {sorted(unknown)}")
    reader = csv.DictReader(io.StringIO(text))
    columns = set(reader.fieldnames or [])
    id_column = mapping.get("id", "id")
    if id_column not in columns:
        raise ValueError(f"id column {id_column!r} not found; columns are {sorted(columns)}")

    contacts = []
    for row in reader:
        values = {f: (row.get(mapping.get(f, f)) or "").strip() for f in CONTACT_FIELDS}
        ts = values.pop("updated_at")
        try:
            updated = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
        except ValueError:
            updated = None
        contacts.append(Contact(**values, updated_at=updated, raw=dict(row)))
    return contacts


def merge_plan_rows(clusters: list[Cluster]) -> Iterator[list[str]]:
    """One row per source record: which cluster it belongs to, whether it survives, and the
    golden values it should end up with. Singletons are included so the plan is complete."""
    yield ["cluster_id", "record_id", "cluster_size", "survivor", *GOLDEN_FIELDS]
    for c in clusters:
        survivor = _survivor(c)
        golden = [_safe(c.golden[f].value) if f in c.golden else "" for f in GOLDEN_FIELDS]
        for member in c.member_ids:
            yield [
                c.id,
                _safe(member),
                str(len(c.member_ids)),
                str(member == survivor).lower(),
                *golden,
            ]


def _survivor(c: Cluster) -> str:
    """The record that already holds most of the golden values - fewest fields to rewrite."""
    sources = Counter(g.source_id for g in c.golden.values())
    return max(c.member_ids, key=lambda m: (sources[m], m)) if sources else c.member_ids[0]


def _safe(value: str) -> str:
    """Neutralise spreadsheet formula injection in values that came from source data."""
    return "'" + value if value[:1] in ("=", "+", "-", "@") else value
