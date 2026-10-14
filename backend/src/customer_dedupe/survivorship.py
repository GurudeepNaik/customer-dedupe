"""Golden record: one value per field, each with the record it came from and the rule that chose
it, so a merge can always be explained and audited."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime

from customer_dedupe.domain import Contact, GoldenField, Profile

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _recency(p: Profile) -> datetime:
    ts = p.contact.updated_at
    if ts is None:
        return _EPOCH
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


Normalised = Callable[[Profile], str]
Original = Callable[[Contact], str]

# (golden field, normalised value used to vote, original value shown to people)
_NAME_FIELDS: tuple[tuple[str, Normalised, Original], ...] = (
    ("first_name", lambda p: p.first_canonical, lambda c: c.first_name),
    ("last_name", lambda p: p.last, lambda c: c.last_name),
)
_VOTED_FIELDS: tuple[tuple[str, Normalised, Original], ...] = (
    ("email", lambda p: p.email, lambda c: c.email),
    ("phone", lambda p: p.phone, lambda c: c.phone),
    ("company", lambda p: p.company, lambda c: c.company),
)
_ADDRESS_FIELDS: tuple[tuple[str, Original], ...] = (
    ("street", lambda c: c.street),
    ("city", lambda c: c.city),
    ("region", lambda c: c.region),
    ("postal_code", lambda c: c.postal_code),
    ("country", lambda c: c.country),
)


def _vote(profiles: list[Profile], key: Normalised, raw: Original) -> GoldenField | None:
    """Most frequent normalised value; ties go to the most recently updated record."""
    present = [p for p in profiles if key(p)]
    if not present:
        return None
    counts = Counter(key(p) for p in present)
    top = max(counts.values())
    winners = [p for p in present if counts[key(p)] == top]
    best = max(winners, key=lambda p: (_recency(p), len(raw(p.contact))))
    rule = f"most frequent ({top} of {len(present)})" if top > 1 else "most recent"
    return GoldenField(raw(best.contact).strip(), best.id, rule)


def _name(profiles: list[Profile], key: Normalised, raw: Original) -> GoldenField | None:
    """Most common canonical name, shown in its fullest written form ('Robert' over 'Bob')."""
    present = [p for p in profiles if key(p)]
    if not present:
        return None
    top_value, top = Counter(key(p) for p in present).most_common(1)[0]
    candidates = [p for p in present if key(p) == top_value]
    best = max(candidates, key=lambda p: (len(raw(p.contact).strip()), _recency(p)))
    rule = f"most common ({top} of {len(present)}), fullest"
    return GoldenField(raw(best.contact).strip(), best.id, rule)


def golden_record(profiles: list[Profile]) -> dict[str, GoldenField]:
    golden: dict[str, GoldenField] = {}
    for fname, key, raw in _NAME_FIELDS:
        if name := _name(profiles, key, raw):
            golden[fname] = name
    for fname, key, raw in _VOTED_FIELDS:
        if voted := _vote(profiles, key, raw):
            golden[fname] = voted

    # Address fields travel together: never a street from one record and a ZIP from another.
    with_address = [p for p in profiles if p.street]
    if with_address:
        latest = max(with_address, key=_recency)
        for fname, raw in _ADDRESS_FIELDS:
            if value := raw(latest.contact).strip():
                golden[fname] = GoldenField(value, latest.id, "most recent complete address")
    return golden
