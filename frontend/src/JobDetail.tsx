import { useEffect, useState } from "react";
import { api, type Cluster, type Job, type Page } from "./api";
import { ReviewQueue } from "./ReviewQueue";
import { DISPLAY_FIELDS, FIELD_LABEL, pct } from "./format";

export function JobDetail({ jobId, onOpen }: { jobId: string; onOpen: (id: string) => void }) {
  const [job, setJob] = useState<Job | null>(null);
  const [tab, setTab] = useState<"review" | "customers">("review");
  const [decisions, setDecisions] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setDecisions(0);
    api.job(jobId).then(setJob, (e: Error) => setError(e.message));
  }, [jobId]);

  if (error) return <p className="error">{error}</p>;
  if (!job) return <p className="muted">Loading…</p>;

  const s = job.stats;
  const rerun = async () => {
    setBusy(true);
    try {
      onOpen((await api.rerun(job.id)).id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <section className="panel">
        <div className="run-head">
          <div>
            <h1>{job.dataset_name}</h1>
            <p className="muted">
              {s.candidate_pairs.toLocaleString()} candidate pairs compared (blocking) ·{" "}
              {s.blocked_by_constraint} merges blocked by conflicts
              {job.decisions_applied > 0 && ` · ${job.decisions_applied} human decisions applied`}
            </p>
          </div>
          <div className="actions">
            <button onClick={rerun} disabled={busy}>
              {busy ? "Re-running…" : `Re-run with decisions${decisions ? ` (+${decisions})` : ""}`}
            </button>
            <a className="button" href={api.planUrl(job.id)}>
              Merge plan CSV
            </a>
          </div>
        </div>
        <div className="cards">
          <Stat label="Records in" value={s.records} />
          <Stat label="Customers out" value={s.clusters} accent="matched" />
          <Stat label="Auto-merged links" value={s.merges} />
          <Stat label="Pairs to review" value={s.reviews} accent="unknown" />
        </div>
        {job.evaluation && (
          <div className="eval">
            <span className="muted small">Against the answer key</span>
            <div>
              <strong>{pct(job.evaluation.precision)}</strong>
              <span className="muted small"> precision — merges that were right</span>
            </div>
            <div>
              <strong>{pct(job.evaluation.recall)}</strong>
              <span className="muted small"> recall — duplicates found automatically</span>
            </div>
            <div>
              <strong>{pct(job.evaluation.recall_after_review)}</strong>
              <span className="muted small"> recall if the review queue is confirmed</span>
            </div>
          </div>
        )}
      </section>

      <nav className="tabs">
        <button className={tab === "review" ? "active" : ""} onClick={() => setTab("review")}>
          Review queue
        </button>
        <button className={tab === "customers" ? "active" : ""} onClick={() => setTab("customers")}>
          Merged customers
        </button>
      </nav>

      {tab === "review" ? (
        <ReviewQueue jobId={job.id} onDecided={() => setDecisions((d) => d + 1)} />
      ) : (
        <Customers jobId={job.id} />
      )}
    </>
  );
}

function Stat({ label, value, accent }: { label: string; value: number; accent?: string }) {
  return (
    <div className={`card ${accent ? `bucket-${accent}` : ""}`}>
      <span className="card-label">{label}</span>
      <span className="card-value">{value.toLocaleString()}</span>
    </div>
  );
}

function Customers({ jobId }: { jobId: string }) {
  const [page, setPage] = useState<Page<Cluster> | null>(null);
  const [offset, setOffset] = useState(0);
  useEffect(() => {
    api.clusters(jobId, offset).then(setPage);
  }, [jobId, offset]);
  if (!page) return <p className="muted">Loading…</p>;
  return (
    <>
      {page.items.map((c) => (
        <section className="panel" key={c.id}>
          <h2>
            {c.golden.first_name?.value} {c.golden.last_name?.value}{" "}
            <span className="muted small">
              · {c.size} records merged
              {c.min_link_score !== null && ` · weakest link ${c.min_link_score.toFixed(1)} bits`}
            </span>
          </h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Golden value</th>
                  {c.members.map((m) => (
                    <th key={m.id}>
                      <code>{m.id}</code> <span className="muted">{m.source}</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {DISPLAY_FIELDS.map((f) => {
                  const g = c.golden[f];
                  return (
                    <tr key={f}>
                      <td className="muted">{FIELD_LABEL[f]}</td>
                      <td>
                        <strong>{g?.value ?? "—"}</strong>
                        {g && <div className="muted small">{g.rule}</div>}
                      </td>
                      {c.members.map((m) => (
                        <td key={m.id} className={g?.source_id === m.id ? "chosen" : ""}>
                          {m[f] || <span className="muted">—</span>}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ))}
      <div className="pager">
        <button disabled={offset === 0} onClick={() => setOffset(offset - 20)}>
          Previous
        </button>
        <span className="muted">
          {offset + 1}–{Math.min(offset + 20, page.total)} of {page.total} merged customers
        </span>
        <button disabled={offset + 20 >= page.total} onClick={() => setOffset(offset + 20)}>
          Next
        </button>
      </div>
    </>
  );
}
