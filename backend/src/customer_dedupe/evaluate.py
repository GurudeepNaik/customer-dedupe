"""Pairwise precision / recall against a ground-truth entity id per record.

precision = of the record pairs we put together, how many really are the same person
recall    = of the record pairs that really are the same person, how many we put together
Pairs sent to review are reported separately: they are neither right nor wrong yet.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations

from customer_dedupe.domain import Result


@dataclass(frozen=True, slots=True)
class Scores:
    true_pairs: int
    predicted_pairs: int
    correct_pairs: int
    review_pairs: int
    review_true: int

    @property
    def precision(self) -> float:
        return self.correct_pairs / self.predicted_pairs if self.predicted_pairs else 1.0

    @property
    def recall(self) -> float:
        return self.correct_pairs / self.true_pairs if self.true_pairs else 1.0

    @property
    def recall_after_review(self) -> float:
        """Recall if a reviewer confirms every true pair in the queue (upper bound)."""
        if not self.true_pairs:
            return 1.0
        return min(1.0, (self.correct_pairs + self.review_true) / self.true_pairs)

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


def _pairs(groups: list[list[str]]) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for g in groups:
        out.update((a, b) if a < b else (b, a) for a, b in combinations(g, 2))
    return out


def evaluate(result: Result, truth: dict[str, str]) -> Scores:
    by_entity: dict[str, list[str]] = defaultdict(list)
    for cid, entity in truth.items():
        by_entity[entity].append(cid)
    true_pairs = _pairs(list(by_entity.values()))
    predicted = _pairs([list(c.member_ids) for c in result.clusters])
    review = {(r.pair.a, r.pair.b) for r in result.review}
    return Scores(
        true_pairs=len(true_pairs),
        predicted_pairs=len(predicted),
        correct_pairs=len(predicted & true_pairs),
        review_pairs=len(review),
        review_true=len(review & (true_pairs - predicted)),
    )
