"""normalise -> block -> score -> cluster (with constraints) -> golden records + review queue."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from customer_dedupe.blocking import candidate_pairs
from customer_dedupe.cluster import ConstrainedUnionFind
from customer_dedupe.compare import Frequencies, Model, score_pair
from customer_dedupe.domain import (
    Agreement,
    Cluster,
    Contact,
    Decision,
    PairScore,
    Priority,
    Profile,
    Result,
    ReviewItem,
    Stats,
)
from customer_dedupe.normalize import profile
from customer_dedupe.survivorship import golden_record

Pair = tuple[str, str]


def _key(a: str, b: str) -> Pair:
    return (a, b) if a <= b else (b, a)


def run(
    contacts: Iterable[Contact],
    model: Model | None = None,
    *,
    must_link: Iterable[Pair] = (),
    cannot_link: Iterable[Pair] = (),
    default_region: str = "US",
    max_block_size: int = 200,
) -> Result:
    model = model or Model()
    items = list(contacts)
    ids = [c.id for c in items]
    if len(ids) != len(set(ids)):
        raise ValueError("contact ids must be unique")

    profiles = [profile(c, default_region) for c in items]
    by_id: dict[str, Profile] = {p.id: p for p in profiles}
    freq = Frequencies(profiles)
    must = {_key(*p) for p in must_link}
    cannot = {_key(*p) for p in cannot_link}
    decided = must | cannot

    index_pairs, oversized = candidate_pairs(profiles, max_block_size)
    scored = [score_pair(profiles[i], profiles[j], model, freq) for i, j in sorted(index_pairs)]

    scored_by_pair = {(p.a, p.b): p for p in scored}

    def conflicts(x: str, y: str) -> bool:
        """Two records conflict if a human said so, or their names disagree once swaps,
        nicknames and typos are accounted for - the same logic used to score them."""
        k = _key(x, y)
        if k in cannot:
            return True
        if k in must:
            return False
        if k not in scored_by_pair:
            scored_by_pair[k] = score_pair(by_id[x], by_id[y], model, freq)
        names = {e.field: e.agreement for e in scored_by_pair[k].evidence}
        return Agreement.DIFFERENT in (names["first_name"], names["last_name"])

    uf = ConstrainedUnionFind(ids)
    link_scores: dict[Pair, float] = {}
    review: list[ReviewItem] = []

    for a, b in sorted(must):
        if a in by_id and b in by_id and (clash := uf.union(a, b, conflicts)) is not None:
            review.append(_blocked(a, b, clash, by_id, model, freq, "confirmed same"))

    merges = sorted(
        (p for p in scored if p.decision is Decision.MERGE and (p.a, p.b) not in decided),
        key=lambda p: (-p.score, p.a, p.b),
    )
    blocked = 0
    for pair in merges:
        clash = uf.union(pair.a, pair.b, conflicts)
        if clash is None:
            link_scores[(pair.a, pair.b)] = pair.score
        elif not uf.same(pair.a, pair.b):
            blocked += 1
            review.append(
                ReviewItem(
                    pair,
                    f"merging would put {clash[0]} and {clash[1]} in one customer, and they"
                    " conflict - kept apart for review",
                )
            )

    for pair in scored:
        if (
            pair.decision is Decision.REVIEW
            and (pair.a, pair.b) not in decided
            and not uf.same(pair.a, pair.b)
        ):
            reason = "; ".join(pair.vetoes) if pair.vetoes else "score between thresholds"
            review.append(ReviewItem(pair, reason, _priority(pair)))

    links_by_root: dict[str, list[float]] = {}
    for (a, _), s in link_scores.items():
        links_by_root.setdefault(uf.find(a), []).append(s)

    clusters = []
    for members in uf.groups():
        member_ids = tuple(sorted(members))
        links = links_by_root.get(uf.find(member_ids[0]), [])
        clusters.append(
            Cluster(
                id=hashlib.sha1("|".join(member_ids).encode()).hexdigest()[:12],
                member_ids=member_ids,
                golden=golden_record([by_id[i] for i in member_ids]),
                min_link_score=min(links) if links else None,
            )
        )
    clusters.sort(key=lambda c: (-len(c.member_ids), c.id))
    review.sort(key=lambda r: (r.priority is Priority.LOW, -r.pair.score))

    stats = Stats(
        records=len(items),
        candidate_pairs=len(scored),
        oversized_blocks=oversized,
        merges=len(link_scores) + len(must),
        reviews=len(review),
        clusters=len(clusters),
        blocked_by_constraint=blocked,
    )
    return Result(tuple(clusters), tuple(review), tuple(scored), stats)


def _blocked(
    a: str,
    b: str,
    clash: Pair,
    by_id: dict[str, Profile],
    model: Model,
    freq: Frequencies,
    label: str,
) -> ReviewItem:
    pair: PairScore = score_pair(by_id[a], by_id[b], model, freq)
    return ReviewItem(pair, f"{label}, but {clash[0]} and {clash[1]} were marked different")


def _priority(pair: PairScore) -> Priority:
    corroborated = any(
        e.field in ("email", "phone", "street")
        and e.agreement in (Agreement.SAME, Agreement.SIMILAR)
        for e in pair.evidence
    )
    return Priority.HIGH if corroborated else Priority.LOW
