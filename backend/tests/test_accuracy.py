"""Accuracy gate on synthetic data with a known answer key.

The matching rules were developed against seeds 11-13; seeds 14 and 15 were not looked at while
tuning and act as a hold-out. Thresholds sit just under what was measured, so a regression in
precision fails the build.
"""

import pytest

from customer_dedupe.compare import Model
from customer_dedupe.engine import run
from customer_dedupe.evaluate import evaluate
from customer_dedupe.synth import generate


@pytest.mark.parametrize("seed", [11, 14, 15])
def test_precision_recall_gate(seed: int) -> None:
    data = generate(seed=seed)
    scores = evaluate(run(data.contacts), data.truth)
    assert scores.precision >= 0.995, scores
    assert scores.recall >= 0.84, scores
    assert scores.recall_after_review >= 0.96, scores


def test_gate_can_fail() -> None:
    """Positive control: the same data scored by the bare probabilistic model, without the
    household / namesake safeguards, must fail the precision gate - otherwise the gate above
    proves nothing about them."""
    data = generate(seed=11)
    bare = evaluate(run(data.contacts, Model(safeguards=False)), data.truth)
    assert bare.precision < 0.995, bare
