import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, type Job } from "./api";
import { JobDetail } from "./JobDetail";
import { pct } from "./format";

function useHashRoute(): [string | null, (id: string | null) => void] {
  const read = () => {
    const match = window.location.hash.match(/^#\/jobs\/(.+)$/);
    return match?.[1] ? decodeURIComponent(match[1]) : null;
  };
  const [jobId, setJobId] = useState(read);
  useEffect(() => {
    const onChange = () => setJobId(read());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  const go = (id: string | null) => {
    window.location.hash = id ? `/jobs/${encodeURIComponent(id)}` : "";
  };
  return [jobId, go];
}

export function App() {
  const [jobId, go] = useHashRoute();
  return (
    <div className="shell">
      <header className="topbar">
        <a href="#" className="brand" onClick={() => go(null)}>
          customer-dedupe
        </a>
        <span className="tagline">Is this the same customer twice? Here is why we think so.</span>
      </header>
      <main>{jobId ? <JobDetail jobId={jobId} onOpen={go} /> : <JobList onOpen={go} />}</main>
    </div>
  );
}

function JobList({ onOpen }: { onOpen: (id: string) => void }) {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.jobs().then(setJobs, (e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  const start = async (fn: () => Promise<Job>) => {
    setBusy(true);
    setError(null);
    try {
      onOpen((await fn()).id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const upload = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    try {
      JSON.parse(String(form.get("mapping")));
    } catch {
      setError("Column mapping is not valid JSON");
      return;
    }
    void start(() => api.upload(form));
  };

  return (
    <>
      <section className="panel hero">
        <div>
          <h1>Deduplication runs</h1>
          <p className="muted">
            The demo deduplicates 3,183 synthetic CRM, ERP and web-shop contacts with planted typos,
            nicknames, households and namesakes — and scores itself against the answer key.
          </p>
        </div>
        <button className="primary" disabled={busy} onClick={() => start(api.demo)}>
          {busy ? "Working…" : "Run the demo"}
        </button>
      </section>
      {error && <p className="error">{error}</p>}

      <section className="panel">
        <h2>Recent runs</h2>
        {jobs === null ? (
          <p className="muted">Loading…</p>
        ) : jobs.length === 0 ? (
          <p className="muted">No runs yet.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Dataset</th>
                  <th className="num">Records</th>
                  <th className="num">Customers</th>
                  <th className="num">To review</th>
                  <th className="num">Precision</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.id} className="clickable" onClick={() => onOpen(j.id)}>
                    <td>
                      <strong>{j.dataset_name}</strong>
                      <div className="muted small">
                        {new Date(j.created_at).toLocaleString()}
                        {j.decisions_applied > 0 && ` · ${j.decisions_applied} decisions applied`}
                      </div>
                    </td>
                    <td className="num">{j.records.toLocaleString()}</td>
                    <td className="num">{j.stats.clusters.toLocaleString()}</td>
                    <td className="num">{j.stats.reviews.toLocaleString()}</td>
                    <td className="num">{j.evaluation ? pct(j.evaluation.precision) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel">
        <h2>Deduplicate your own contacts</h2>
        <form className="upload" onSubmit={upload}>
          <label>
            Name
            <input name="name" defaultValue="My contacts" maxLength={200} />
          </label>
          <label>
            CSV file
            <input type="file" name="file" accept=".csv,text/csv" required />
          </label>
          <label className="wide">
            Column mapping (contact field → your column; omit fields whose column has the same name)
            <textarea
              name="mapping"
              rows={4}
              spellCheck={false}
              defaultValue={JSON.stringify({ id: "id", first_name: "first_name", email: "email" }, null, 2)}
            />
          </label>
          <div className="wide">
            <button className="primary" disabled={busy}>
              Find duplicates
            </button>
          </div>
        </form>
      </section>
    </>
  );
}
