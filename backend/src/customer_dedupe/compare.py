"""Pairwise scoring with Fellegi-Sunter match weights.

For each field, m = P(fields agree | same person) and u = P(fields agree | different people).
Agreement adds log2(m/u) bits of evidence, disagreement adds log2((1-m)/(1-u)) (negative),
and a missing value adds nothing. Term-frequency adjustment raises u for common values, so two
'Smith's agreeing is worth less than two 'Okonkwo's agreeing.

Every score is fully explained by its Evidence list: a reviewer can see exactly which fields
pushed a pair over the line.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace

from rapidfuzz import fuzz
from rapidfuzz.distance import OSA, JaroWinkler

from customer_dedupe.domain import Agreement, Decision, Evidence, PairScore, Profile
from customer_dedupe.nicknames import canonical_first_name, name_forms


@dataclass(frozen=True, slots=True)
class FieldModel:
    m: float
    u: float
    term_frequency: bool = False


@dataclass(frozen=True, slots=True)
class Model:
    fields: dict[str, FieldModel] = field(
        default_factory=lambda: {
            "email": FieldModel(m=0.85, u=0.0001, term_frequency=True),
            "phone": FieldModel(m=0.80, u=0.0005, term_frequency=True),
            "first_name": FieldModel(m=0.92, u=0.02, term_frequency=True),
            "last_name": FieldModel(m=0.95, u=0.01, term_frequency=True),
            "street": FieldModel(m=0.75, u=0.001),
            "postal_code": FieldModel(m=0.80, u=0.01, term_frequency=True),
            "city": FieldModel(m=0.85, u=0.05, term_frequency=True),
            "company": FieldModel(m=0.70, u=0.01, term_frequency=True),
        }
    )
    merge_threshold: float = 18.0
    review_threshold: float = 8.0
    # Household / namesake rules on top of the pure probabilistic score. Only switched off to
    # measure what they are worth.
    safeguards: bool = True


_PROFILE_ATTR = {
    "email": "email",
    "phone": "phone",
    "first_name": "first_canonical",
    "last_name": "last",
    "street": "street",
    "postal_code": "postal",
    "city": "city",
    "company": "company",
}


class Frequencies:
    """Relative frequency of each normalised value per field across the dataset."""

    def __init__(self, profiles: Iterable[Profile]) -> None:
        items = list(profiles)
        self.n = max(len(items), 1)
        self.counts: dict[str, Counter[str]] = {
            f: Counter(v for p in items if (v := getattr(p, attr)))
            for f, attr in _PROFILE_ATTR.items()
        }

    def of(self, field_name: str, value: str) -> float:
        """How common the value is among *other* records: the pair being compared accounts
        for two occurrences itself, so a value seen only in this pair is not 'common'."""
        return max(0, self.counts[field_name][value] - 2) / self.n


# ----------------------------------------------------------------------------- comparators

Comparison = tuple[Agreement, float]


def _jw(a: str, b: str) -> float:
    return float(JaroWinkler.similarity(a, b))


def compare_first(a: Profile, b: Profile) -> Comparison:
    if not a.first or not b.first:
        return Agreement.UNKNOWN, 0.0
    if a.first_canonical == b.first_canonical:
        return Agreement.SAME, 1.0
    for x, y in ((a, b), (b, a)):
        if len(x.first) == 1 and x.first in (y.first[:1], y.first_canonical[:1]):
            return Agreement.SIMILAR, 0.5  # 'J' vs 'John', 'M' vs 'Peggy' (Margaret)
    # Typos happen in what was written, so compare each written name with every accepted
    # spelling of the other ('Kahy' vs Katherine's forms finds 'Kathy') - but never variant
    # against variant, or Nicholas ('Nicky') would be a typo of Victoria ('Vicky').
    pairs = [(a.first, y) for y in name_forms(b.first_canonical, b.first)] + [
        (b.first, x) for x in name_forms(a.first_canonical, a.first)
    ]
    sim = max(_jw(x, y) for x, y in pairs)
    typo = any(OSA.distance(x, y) <= 1 for x, y in pairs if min(len(x), len(y)) >= 4)
    return (Agreement.SIMILAR, sim) if typo or sim >= 0.92 else (Agreement.DIFFERENT, sim)


def compare_last(a: Profile, b: Profile) -> Comparison:
    if not a.last or not b.last:
        return Agreement.UNKNOWN, 0.0
    if a.last == b.last:
        return Agreement.SAME, 1.0
    ta, tb = set(a.last.split()), set(b.last.split())
    if ta <= tb or tb <= ta:
        return Agreement.SIMILAR, 0.9  # 'garcia' vs 'garcia lopez'
    sim = _jw(a.last, b.last)
    typo = min(len(a.last), len(b.last)) >= 4 and OSA.distance(a.last, b.last) <= 1
    return (Agreement.SIMILAR, sim) if typo or sim >= 0.92 else (Agreement.DIFFERENT, sim)


def compare_exact(attr: str) -> Callable[[Profile, Profile], Comparison]:
    def cmp(a: Profile, b: Profile) -> Comparison:
        va, vb = getattr(a, attr), getattr(b, attr)
        if not va or not vb:
            return Agreement.UNKNOWN, 0.0
        return (Agreement.SAME, 1.0) if va == vb else (Agreement.DIFFERENT, 0.0)

    return cmp


def compare_phone(a: Profile, b: Profile) -> Comparison:
    if not a.phone or not b.phone:
        return Agreement.UNKNOWN, 0.0
    if a.phone == b.phone:
        return Agreement.SAME, 1.0
    da, db = re.sub(r"\D", "", a.phone), re.sub(r"\D", "", b.phone)
    if len(da) >= 7 and da[-7:] == db[-7:]:
        return Agreement.SIMILAR, 0.7  # same local number, area/country code missing on one
    return Agreement.DIFFERENT, 0.0


def compare_street(a: Profile, b: Profile) -> Comparison:
    if not a.street or not b.street:
        return Agreement.UNKNOWN, 0.0
    num_a = re.match(r"\d+", a.street)
    num_b = re.match(r"\d+", b.street)
    if num_a and num_b and num_a.group() != num_b.group():
        return Agreement.DIFFERENT, 0.0
    sim = fuzz.token_set_ratio(a.street, b.street) / 100
    if sim >= 0.95:
        return Agreement.SAME, sim
    return (Agreement.SIMILAR, sim) if sim >= 0.8 else (Agreement.DIFFERENT, sim)


def compare_fuzzy(
    attr: str, same: float, similar: float
) -> Callable[[Profile, Profile], Comparison]:
    def cmp(a: Profile, b: Profile) -> Comparison:
        va, vb = getattr(a, attr), getattr(b, attr)
        if not va or not vb:
            return Agreement.UNKNOWN, 0.0
        sim = fuzz.token_set_ratio(va, vb) / 100
        if sim >= same:
            return Agreement.SAME, sim
        return (Agreement.SIMILAR, sim) if sim >= similar else (Agreement.DIFFERENT, sim)

    return cmp


COMPARATORS: dict[str, Callable[[Profile, Profile], Comparison]] = {
    "email": compare_exact("email"),
    "phone": compare_phone,
    "first_name": compare_first,
    "last_name": compare_last,
    "street": compare_street,
    "postal_code": compare_exact("postal"),
    "city": compare_fuzzy("city", 0.97, 0.9),
    "company": compare_fuzzy("company", 0.95, 0.85),
}

_DISPLAY = {
    "first_name": "first",
    "last_name": "last",
    "postal_code": "postal",
}


# ----------------------------------------------------------------------------- scoring


def _swapped(a: Profile, b: Profile) -> bool:
    """First and last name entered the other way round in one system - possibly with a typo
    or nickname on top, so compare the crossed fields with the normal comparators."""
    if not (a.first and a.last and b.first and b.last):
        return False
    if compare_first(a, b)[0] is not Agreement.DIFFERENT:
        return False
    crossed = replace(
        b,
        first=b.last.split(" ")[0],
        first_canonical=canonical_first_name(b.last.split(" ")[0]),
        last=b.first,
    )
    return (
        compare_first(a, crossed)[0] is not Agreement.DIFFERENT
        and compare_last(a, crossed)[0] is not Agreement.DIFFERENT
    )


def score_pair(a: Profile, b: Profile, model: Model, freq: Frequencies) -> PairScore:
    # Canonical order: the score of a pair must not depend on which record came first.
    if b.id < a.id:
        a, b = b, a
    swapped = _swapped(a, b) or _swapped(b, a)
    evidence: list[Evidence] = []
    for name, fm in model.fields.items():
        if swapped and name in ("first_name", "last_name"):
            agreement, sim = Agreement.SAME, 1.0
        else:
            agreement, sim = COMPARATORS[name](a, b)
        attr = _DISPLAY.get(name, _PROFILE_ATTR[name])
        evidence.append(
            Evidence(
                field=name,
                agreement=agreement,
                similarity=round(sim, 3),
                weight=round(_weight(name, fm, agreement, sim, a, b, freq), 3),
                left=getattr(a, attr),
                right=getattr(b, attr),
            )
        )

    score = round(sum(e.weight for e in evidence), 3)
    vetoes = _vetoes(evidence) if model.safeguards else ()
    if model.safeguards and _clearly_different(evidence):
        decision = Decision.DISTINCT
    elif score >= model.merge_threshold and not vetoes:
        decision = Decision.MERGE
    elif score >= model.review_threshold:
        decision = Decision.REVIEW
    else:
        decision = Decision.DISTINCT
    x, y = sorted((a.id, b.id))
    return PairScore(x, y, score, decision, tuple(evidence), vetoes)


def _weight(
    name: str,
    fm: FieldModel,
    agreement: Agreement,
    sim: float,
    a: Profile,
    b: Profile,
    freq: Frequencies,
) -> float:
    if agreement is Agreement.UNKNOWN:
        return 0.0
    u = fm.u
    if fm.term_frequency:
        # Near-matches have two values; use the more common one (less evidence) - and keep
        # the result independent of argument order.
        attr = _PROFILE_ATTR[name]
        u = max(u, freq.of(name, getattr(a, attr)), freq.of(name, getattr(b, attr)))
    u = min(u, 0.5)
    agree = math.log2(fm.m / u)
    disagree = math.log2((1 - fm.m) / (1 - fm.u))
    if agreement is Agreement.SAME:
        return agree
    if agreement is Agreement.DIFFERENT:
        return disagree
    # SIMILAR: partial credit between disagreement and agreement.
    return disagree + (agree - disagree) * max(0.0, min(1.0, sim)) * 0.8


def _clearly_different(evidence: list[Evidence]) -> bool:
    """Decisive contrary evidence, so the pair does not even need a human:
    - first names that are not variants, initials or typos of each other ('Chloe' vs 'Wei')
      - the classic household case, where address and landline are shared;
    - or nothing corroborates identity and at least two contact fields actively disagree."""
    by_field = {e.field: e for e in evidence}
    first = by_field["first_name"]
    if first.agreement is Agreement.DIFFERENT and first.similarity < 0.8:
        return True
    contact = [by_field[f].agreement for f in ("email", "phone", "street")]
    corroborated = any(a in (Agreement.SAME, Agreement.SIMILAR) for a in contact)
    return not corroborated and contact.count(Agreement.DIFFERENT) >= 2


def _vetoes(evidence: list[Evidence]) -> tuple[str, ...]:
    """Contact details are shared by households and colleagues; identity is not.
    A pair whose names clearly disagree can be reviewed, but never merged automatically."""
    by_field = {e.field: e for e in evidence}
    vetoes = []
    if by_field["first_name"].agreement is Agreement.DIFFERENT:
        vetoes.append("first names differ")
    if by_field["last_name"].agreement is Agreement.DIFFERENT:
        vetoes.append("last names differ")
    # 'M.' or 'Mark' vs 'Mary' at one address may be a typo or a spouse: households share
    # address and landline, rarely a personal email - so only an email settles it.
    first = by_field["first_name"]
    if first.agreement is Agreement.SIMILAR and by_field["email"].agreement is not Agreement.SAME:
        initial = min(len(first.left), len(first.right)) == 1
        vetoes.append("first name is only an initial" if initial else "first names only similar")
    # Two 'Steven Garcia's in the same ZIP are common; name + place alone is not identity.
    corroborated = any(
        by_field[f].agreement in (Agreement.SAME, Agreement.SIMILAR)
        for f in ("email", "phone", "street")
    )
    if not corroborated:
        vetoes.append("no shared email, phone or street")
    return tuple(vetoes)
