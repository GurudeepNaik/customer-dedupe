import { useEffect, useState } from "react";
import { api, type Evidence, type Page, type ReviewItem } from "./api";
import { FIELD_LABEL } from "./format";

const PAGE = 10;

export function ReviewQueue({ jobId, onDecided }: { jobId: string; onDecided: () => void }) {
  const [priority, setPriority] = useState<"high" | "low">("high");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<Page<ReviewItem> | null>(null);
  const [local, setLocal] = useState<Record<number, boolean>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setPage(null);
    api.review(jobId, priority, offset, PAGE).then(setPage, (e: Error) => setError(e.message));
  }, [jobId, priority, offset]);

  const decide = async (item: ReviewItem, same: boolean) => {
    try {
      await api.decide(jobId, item.a.id, item.b.id, same);
      setLocal((d) => ({ ...d, [item.id]: same }));
      onDecided();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <section className="panel">
      <div className="run-head">
        <div className="segmented">
          {(["high", "low"] as const).map((p) => (
            <button
              key={p}
              className={priority === p ? "active" : ""}
              onClick={() => {
                setPriority(p);
                setOffset(0);
              }}
            >
              {p === "high" ? "Likely duplicates" : "Possible duplicates"}
            </button>
          ))}
        </div>
        <p className="muted small">
          {priority === "high"
            ? "A shared email, phone or street supports these; a safety rule held the merge back."
            : "Only the name and place agree — often a namesake, sometimes someone who moved."}
        </p>
      </div>
      {error && <p className="error">{error}</p>}
      {!page ? (
        <p className="muted">Loading…</p>
      ) : page.items.length === 0 ? (
        <p className="muted">Nothing to review here.</p>
      ) : (
        page.items.map((item) => {
          const decided = local[item.id] ?? item.decided;
          return (
            <article key={item.id} className="review">
              <header>
                <span className={`pill bucket-${item.priority === "high" ? "matched" : "unknown"}`}>
                  {item.score.toFixed(1)} bits
                </span>
                <span className="muted small">{item.reason}</span>
              </header>
              <EvidenceTable evidence={item.evidence} a={item.a.id} b={item.b.id} />
              <footer>
                {decided === null || decided === undefined ? (
                  <>
                    <button className="primary" onClick={() => decide(item, true)}>
                      Same customer
                    </button>
                    <button onClick={() => decide(item, false)}>Different people</button>
                  </>
                ) : (
                  <span className={decided ? "ok" : "muted"}>
                    Marked {decided ? "same customer" : "different people"} — applied on re-run
                  </span>
                )}
              </footer>
            </article>
          );
        })
      )}
      {page && page.total > PAGE && (
        <div className="pager">
          <button disabled={offset === 0} onClick={() => setOffset(offset - PAGE)}>
            Previous
          </button>
          <span className="muted">
            {offset + 1}–{Math.min(offset + PAGE, page.total)} of {page.total}
          </span>
          <button disabled={offset + PAGE >= page.total} onClick={() => setOffset(offset + PAGE)}>
            Next
          </button>
        </div>
      )}
    </section>
  );
}

function EvidenceTable({ evidence, a, b }: { evidence: Evidence[]; a: string; b: string }) {
  const max = Math.max(...evidence.map((e) => Math.abs(e.weight)), 1);
  return (
    <div className="table-wrap">
      <table className="evidence">
        <thead>
          <tr>
            <th>Field</th>
            <th>
              <code>{a}</code>
            </th>
            <th>
              <code>{b}</code>
            </th>
            <th>Agreement</th>
            <th className="num">Evidence (bits)</th>
          </tr>
        </thead>
        <tbody>
          {evidence.map((e) => (
            <tr key={e.field} className={e.agreement === "unknown" ? "faint" : ""}>
              <td className="muted">{FIELD_LABEL[e.field] ?? e.field}</td>
              <td>{e.left || "—"}</td>
              <td>{e.right || "—"}</td>
              <td>
                <span className={`agree agree-${e.agreement}`}>{e.agreement}</span>
              </td>
              <td className="num weight">
                <span
                  className={`bar ${e.weight < 0 ? "neg" : "pos"}`}
                  style={{ width: `${(Math.abs(e.weight) / max) * 60}px` }}
                />
                {e.weight > 0 ? "+" : ""}
                {e.weight.toFixed(1)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
