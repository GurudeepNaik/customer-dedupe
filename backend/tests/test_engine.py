from datetime import UTC, datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from customer_dedupe.cluster import ConstrainedUnionFind
from customer_dedupe.domain import Contact, Priority
from customer_dedupe.engine import run

ADDR = dict(street="12 Oak Street", city="Kansas City", postal_code="64111", phone="8165172606")


def test_chaining_through_a_shared_phone_is_blocked() -> None:
    # bob~rob (same person); rob shares the family phone with rachel. Plain union-find would
    # make all three one customer.
    contacts = [
        Contact("bob", first_name="Bob", last_name="Smith", email="bob@x.io", **ADDR),
        Contact("rob", first_name="Robert", last_name="Smith", email="bob@x.io", **ADDR),
        Contact("rachel", first_name="Rachel", last_name="Smith", **ADDR),
    ]
    res = run(contacts)
    groups = {frozenset(c.member_ids) for c in res.clusters}
    assert frozenset({"bob", "rob"}) in groups
    assert frozenset({"rachel"}) in groups


def test_union_find_refuses_conflicting_union() -> None:
    uf = ConstrainedUnionFind(["a", "b", "c"])
    assert uf.union("a", "b", lambda x, y: False) is None
    clash = uf.union("b", "c", lambda x, y: {x, y} == {"a", "c"})
    assert clash == ("a", "c")
    assert not uf.same("a", "c")


def test_human_decisions_override_the_model() -> None:
    a = Contact("a", first_name="J", last_name="Doe", street="1 Main St", postal_code="10001")
    b = Contact("b", first_name="Jane", last_name="Doe", street="1 Main St", postal_code="10001")
    assert len(run([a, b]).clusters) == 2
    merged = run([a, b], must_link=[("a", "b")])
    assert len(merged.clusters) == 1 and not merged.review

    x = Contact("x", first_name="Robert", last_name="Smith", email="r@x.io", **ADDR)
    y = Contact("y", first_name="Bob", last_name="Smith", email="r@x.io", **ADDR)
    assert len(run([x, y]).clusters) == 1
    kept_apart = run([x, y], cannot_link=[("y", "x")])
    assert len(kept_apart.clusters) == 2 and not kept_apart.review


def test_golden_record_keeps_address_together_and_records_lineage() -> None:
    old = datetime(2024, 1, 1, tzinfo=UTC)
    new = datetime(2025, 6, 1, tzinfo=UTC)
    contacts = [
        Contact("1", first_name="Bob", last_name="Smith", email="bob@x.io",
                street="12 Oak Street", city="Kansas City", postal_code="64111", updated_at=old),
        Contact("2", first_name="Robert", last_name="Smith", email="bob@x.io",
                street="9 Pine Rd", city="Denver", postal_code="80202", updated_at=new),
    ]  # fmt: skip
    [cluster] = run(contacts).clusters
    g = cluster.golden
    assert g["first_name"].value == "Robert"  # fullest form of the common canonical name
    assert (g["street"].value, g["city"].value, g["postal_code"].value) == (
        "9 Pine Rd",
        "Denver",
        "80202",
    )
    assert {g["street"].source_id, g["city"].source_id, g["postal_code"].source_id} == {"2"}
    assert g["email"].rule.startswith("most frequent")


LEE = dict(phone="3035550100", street="5 Elm St", postal_code="80202")


def test_review_queue_puts_corroborated_pairs_first() -> None:
    contacts = [
        Contact("1", first_name="Steven", last_name="Garcia", postal_code="80228", city="Denver"),
        Contact("2", first_name="Steven", last_name="Garcia", postal_code="80228", city="Denver"),
        Contact("3", first_name="Mark", last_name="Lee", **LEE),
        Contact("4", first_name="Marc", last_name="Lee", **LEE),
    ]
    review = run(contacts).review
    assert [r.priority for r in review] == [Priority.HIGH, Priority.LOW]


def test_rejects_duplicate_ids() -> None:
    with pytest.raises(ValueError):
        run([Contact("1"), Contact("1")])


HOME = dict(street="1 Main St", postal_code="10001")
names = st.sampled_from(["Bob", "Robert", "Rob", "Rachel", "Ann", "Anne", "J", ""])
lasts = st.sampled_from(["Smith", "Smyth", "Lee", ""])
emails = st.sampled_from(["", "a@x.io", "b@x.io"])
phones = st.sampled_from(["", "8165172606", "3035550100"])


@settings(max_examples=150, deadline=None)
@given(
    st.lists(st.tuples(names, lasts, emails, phones), min_size=0, max_size=25),
    st.lists(st.tuples(st.integers(0, 24), st.integers(0, 24)), max_size=5),
)
def test_every_record_lands_in_exactly_one_cluster_and_cannot_links_hold(
    rows: list[tuple[str, str, str, str]], rejects: list[tuple[int, int]]
) -> None:
    contacts = [
        Contact(str(i), first_name=f, last_name=last, email=e, phone=p, **HOME)
        for i, (f, last, e, p) in enumerate(rows)
    ]
    cannot = [(str(a), str(b)) for a, b in rejects if a != b and a < len(rows) and b < len(rows)]
    res = run(contacts, cannot_link=cannot)
    placed = [m for c in res.clusters for m in c.member_ids]
    assert sorted(placed) == sorted(c.id for c in contacts)
    where = {m: c.id for c in res.clusters for m in c.member_ids}
    for a, b in cannot:
        assert where[a] != where[b]


def test_result_does_not_depend_on_input_order() -> None:
    import random

    from customer_dedupe.synth import generate

    data = generate(people=400, seed=3)
    shuffled = list(data.contacts)
    random.Random(1).shuffle(shuffled)
    a, b = run(data.contacts), run(shuffled)
    assert sorted(c.member_ids for c in a.clusters) == sorted(c.member_ids for c in b.clusters)
    assert {(r.pair.a, r.pair.b) for r in a.review} == {(r.pair.a, r.pair.b) for r in b.review}
