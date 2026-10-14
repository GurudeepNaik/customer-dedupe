from customer_dedupe.compare import Frequencies, Model, score_pair
from customer_dedupe.domain import Agreement, Contact, Decision, PairScore
from customer_dedupe.normalize import profile


def score(a: Contact, b: Contact, *population: Contact) -> PairScore:
    profiles = [profile(c) for c in (a, b, *population)]
    return score_pair(profiles[0], profiles[1], Model(), Frequencies(profiles))


def c(id: str, **kw: str) -> Contact:
    return Contact(id=id, **kw)


def ev(p: PairScore, field: str) -> Agreement:
    return next(e.agreement for e in p.evidence if e.field == field)


BOB = dict(last_name="Smith", email="bob.smith@gmail.com", phone="816-517-2606",
           street="12 Oak Street", city="Kansas City", postal_code="64111")  # fmt: skip


def test_same_person_different_formatting_merges() -> None:
    p = score(
        c("1", first_name="Robert", **BOB),
        c("2", first_name="BOB", last_name="smith", email="BobSmith+orders@gmail.com",
          phone="(816) 517 2606", street="12 Oak St", postal_code="64111-9000"),
    )  # fmt: skip
    assert p.decision is Decision.MERGE, p
    assert ev(p, "first_name") is Agreement.SAME
    assert ev(p, "email") is Agreement.SAME


def test_missing_data_is_unknown_not_contrary() -> None:
    p = score(c("1", first_name="Robert", **BOB), c("2", first_name="Robert", last_name="Smith"))
    assert ev(p, "email") is Agreement.UNKNOWN
    assert next(e.weight for e in p.evidence if e.field == "email") == 0


def test_household_member_is_distinct_not_merged() -> None:
    household = dict(BOB, email="")
    p = score(c("1", first_name="Robert", **household), c("2", first_name="Chloe", **household))
    assert p.decision is Decision.DISTINCT


def test_namesake_in_same_zip_is_never_auto_merged() -> None:
    p = score(
        c("1", first_name="Steven", last_name="Garcia", postal_code="80228", city="Denver"),
        c("2", first_name="Steven", last_name="Garcia", postal_code="80228", city="Denver"),
    )
    assert p.decision is not Decision.MERGE
    assert "no shared email, phone or street" in p.vetoes


def test_swapped_first_and_last_name_with_typo() -> None:
    p = score(
        c("1", first_name="Edward", last_name="Lindqvist", email="e.l@acme.com"),
        c("2", first_name="LINDQIVST", last_name="Eddie", email="e.l@acme.com"),
    )
    assert ev(p, "first_name") is Agreement.SAME
    assert ev(p, "last_name") is Agreement.SAME
    assert p.decision is Decision.MERGE


def test_nickname_variants_are_not_typos_of_each_other() -> None:
    # 'Nicky' (Nicholas) is one keystroke from 'Vicky' (Victoria): must stay different.
    p = score(c("1", first_name="Nicholas", last_name="Carter"),
              c("2", first_name="Victoria", last_name="Carter"))  # fmt: skip
    assert ev(p, "first_name") is Agreement.DIFFERENT


def test_typo_in_nickname_matches_but_needs_email_to_merge() -> None:
    same_place = dict(
        last_name="Miller", phone="5125550188", street="9 Elm Rd", postal_code="78712"
    )
    without_email = score(
        c("1", first_name="Katie", **same_place), c("2", first_name="Kahy", **same_place)
    )
    assert ev(without_email, "first_name") is Agreement.SIMILAR
    assert without_email.decision is Decision.REVIEW
    with_email = score(
        c("1", first_name="Katie", email="k@x.io", **same_place),
        c("2", first_name="Kahy", email="k@x.io", **same_place),
    )
    assert with_email.decision is Decision.MERGE


def test_common_values_carry_less_weight() -> None:
    crowd = [c(str(i), first_name="X", last_name="Smith") for i in range(10, 60)]
    common = score(
        c("1", first_name="Ann", last_name="Smith"),
        c("2", first_name="Ann", last_name="Smith"),
        *crowd,
    )
    rare = score(
        c("1", first_name="Ann", last_name="Okonkwo"),
        c("2", first_name="Ann", last_name="Okonkwo"),
        *crowd,
    )
    w = lambda p: next(e.weight for e in p.evidence if e.field == "last_name")  # noqa: E731
    assert w(rare) > w(common) + 4


def test_score_is_the_sum_of_its_evidence() -> None:
    p = score(c("1", first_name="Robert", **BOB), c("2", first_name="Rob", **BOB))
    assert abs(p.score - sum(e.weight for e in p.evidence)) < 0.01
