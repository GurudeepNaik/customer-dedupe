"""`dedupe run contacts.csv --plan merge-plan.csv` - no server needed."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Annotated

import typer

from customer_dedupe import synth
from customer_dedupe.compare import Model
from customer_dedupe.engine import run as run_engine
from customer_dedupe.evaluate import evaluate as score
from customer_dedupe.io import CONTACT_FIELDS, merge_plan_rows, read_contacts

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command()
def run(
    contacts_csv: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    mapping: Annotated[str, typer.Option(help='JSON, e.g. {"id": "ContactId"}')] = "{}",
    plan: Annotated[Path | None, typer.Option(help="Write the merge plan CSV here")] = None,
    review: Annotated[Path | None, typer.Option(help="Write the review queue CSV here")] = None,
    region: Annotated[str, typer.Option(help="Default phone region")] = "US",
) -> None:
    """Find duplicates in a CSV of contacts."""
    contacts = read_contacts(contacts_csv.read_text(encoding="utf-8-sig"), json.loads(mapping))
    result = run_engine(contacts, default_region=region)
    s = result.stats
    dupes = sum(1 for c in result.clusters if len(c.member_ids) > 1)
    typer.echo(
        f"{s.records} records -> {s.clusters} customers ({dupes} with duplicates)\n"
        f"{s.candidate_pairs} candidate pairs compared, {s.merges} merges, "
        f"{s.reviews} pairs for review, {s.blocked_by_constraint} merges blocked by conflicts"
    )
    if s.oversized_blocks:
        typer.echo(
            f"warning: {s.oversized_blocks} oversized blocks skipped (shared mailbox/phone?)"
        )
    if plan:
        with plan.open("w", newline="") as fh:
            csv.writer(fh).writerows(merge_plan_rows(list(result.clusters)))
        typer.echo(f"merge plan -> {plan}")
    if review:
        with review.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["priority", "score", "a", "b", "reason", "evidence"])
            for r in result.review:
                ev = "; ".join(
                    f"{e.field}:{e.agreement.value}:{e.weight:+.1f}"
                    for e in r.pair.evidence
                    if e.agreement.value != "unknown"
                )
                w.writerow([r.priority.value, r.pair.score, r.pair.a, r.pair.b, r.reason, ev])
        typer.echo(f"review queue -> {review}")


@app.command()
def demo(out: Annotated[Path, typer.Option()] = Path("demo-contacts.csv"), seed: int = 11) -> None:
    """Write a synthetic contacts CSV (with an extra entity_id answer-key column)."""
    data = synth.generate(seed=seed)
    with out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([*CONTACT_FIELDS, "entity_id"])
        for c in data.contacts:
            values = [getattr(c, f) for f in CONTACT_FIELDS]
            values[-1] = c.updated_at.isoformat() if c.updated_at else ""
            w.writerow([*values, data.truth[c.id]])
    typer.echo(f"wrote {len(data.contacts)} contacts to {out}")


@app.command()
def benchmark(
    seeds: Annotated[str, typer.Option()] = "11,12,13,14,15",
    bare: Annotated[bool, typer.Option(help="Disable household/namesake safeguards")] = False,
) -> None:
    """Precision / recall on synthetic data with a known answer key."""
    for seed in (int(s) for s in seeds.split(",")):
        data = synth.generate(seed=seed)
        result = run_engine(data.contacts, Model(safeguards=not bare))
        sc = score(result, data.truth)
        typer.echo(
            f"seed {seed}: {len(data.contacts)} records  precision {sc.precision:.4f}  "
            f"recall {sc.recall:.4f}  review {sc.review_pairs} ({sc.review_true} true)  "
            f"recall after review {sc.recall_after_review:.4f}"
        )


if __name__ == "__main__":
    app()
