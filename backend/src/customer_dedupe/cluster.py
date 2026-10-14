"""Clustering with constraints.

Plain union-find is transitive: if A~B and B~C then A, B and C become one customer even when
A and C are clearly different people ('Bob Smith' -> shared family phone -> 'Rachel Smith').
Here a union is refused when any record on one side conflicts with any record on the other
(names disagree, or a human said 'different'), and the refused link goes to review instead.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable


class ConstrainedUnionFind:
    def __init__(self, ids: Iterable[str]) -> None:
        self.parent: dict[str, str] = {i: i for i in ids}
        self.members: dict[str, set[str]] = {i: {i} for i in self.parent}

    def find(self, x: str) -> str:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def same(self, a: str, b: str) -> bool:
        return self.find(a) == self.find(b)

    def union(
        self, a: str, b: str, conflicts: Callable[[str, str], bool]
    ) -> tuple[str, str] | None:
        """Merge the clusters of a and b unless a cross-cluster conflict exists.
        Returns None on success (or if already merged), else the conflicting pair."""
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return None
        for x in self.members[ra]:
            for y in self.members[rb]:
                if conflicts(x, y):
                    return (x, y)
        if len(self.members[ra]) < len(self.members[rb]):
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.members[ra] |= self.members.pop(rb)
        return None

    def groups(self) -> list[set[str]]:
        return [set(m) for m in self.members.values()]
