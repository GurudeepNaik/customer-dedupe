"""Blocking: only compare records that share at least one cheap key. Comparing every pair is
O(n^2) - 50,000 contacts is 1.25 billion comparisons. Blocking keeps it near-linear while the
keys are chosen so a true duplicate almost always shares at least one of them."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator

import jellyfish

from customer_dedupe.domain import Profile


def _sound(text: str) -> str:
    return str(jellyfish.metaphone(text)) if text else ""


def keys(p: Profile) -> Iterator[str]:
    if p.email:
        yield f"email:{p.email}"
        yield f"email-local:{p.email.split('@')[0]}"
    if p.phone:
        yield f"phone:{p.phone[-7:]}"
    last = _sound(p.last.split(" ")[-1]) if p.last else ""
    first = _sound(p.first_canonical)
    if last and p.postal:
        yield f"last-postal:{last}:{p.postal}"
    if last and first:
        # Scoped to a ZIP prefix (~a metro area) so 'John Smith' is not one giant block;
        # someone who moved further away is still found through their email or phone.
        area = p.postal[:3]
        yield f"name:{first}:{last}:{area}"
        yield f"name:{last}:{first}:{area}"  # first/last swapped between systems
    if last and p.company:
        yield f"last-company:{last}:{p.company}"
    if p.street and p.postal:
        number = p.street.split(" ")[0]
        yield f"addr:{number}:{p.postal}"


def candidate_pairs(
    profiles: Iterable[Profile], max_block_size: int = 200
) -> tuple[set[tuple[int, int]], int]:
    """Index pairs (i < j) sharing a key. Blocks larger than max_block_size (e.g. a shared
    'info@' mailbox or a switchboard number) are skipped and counted, not silently compared."""
    blocks: dict[str, list[int]] = defaultdict(list)
    for i, p in enumerate(profiles):
        for k in set(keys(p)):
            blocks[k].append(i)
    pairs: set[tuple[int, int]] = set()
    oversized = 0
    for members in blocks.values():
        if len(members) > max_block_size:
            oversized += 1
            continue
        for x in range(len(members)):
            for y in range(x + 1, len(members)):
                pairs.add((members[x], members[y]))
    return pairs, oversized
