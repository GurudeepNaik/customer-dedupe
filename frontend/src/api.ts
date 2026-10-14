export interface Stats {
  records: number;
  candidate_pairs: number;
  oversized_blocks: number;
  merges: number;
  reviews: number;
  clusters: number;
  blocked_by_constraint: number;
}

export interface Evaluation {
  precision: number;
  recall: number;
  recall_after_review: number;
  true_pairs: number;
  predicted_pairs: number;
  correct_pairs: number;
  review_pairs: number;
  review_true: number;
}

export interface Job {
  id: string;
  dataset_id: string;
  dataset_name: string;
  records: number;
  created_at: string;
  decisions_applied: number;
  stats: Stats;
  evaluation: Evaluation | null;
}

export type Contact = Record<string, string | null> & { id: string };

export interface GoldenField {
  value: string;
  source_id: string;
  rule: string;
}

export interface Cluster {
  id: string;
  size: number;
  golden: Record<string, GoldenField>;
  min_link_score: number | null;
  members: Contact[];
}

export interface Evidence {
  field: string;
  agreement: "same" | "similar" | "different" | "unknown";
  similarity: number;
  weight: number;
  left: string;
  right: string;
}

export interface ReviewItem {
  id: number;
  score: number;
  priority: "high" | "low";
  reason: string;
  evidence: Evidence[];
  a: Contact;
  b: Contact;
  decided: boolean | null;
}

export interface Page<T> {
  total: number;
  items: T[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) throw new Error(`${res.status}: ${(await res.text()).slice(0, 300)}`);
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

const enc = encodeURIComponent;

export const api = {
  jobs: () => request<Job[]>("/api/jobs"),
  job: (id: string) => request<Job>(`/api/jobs/${enc(id)}`),
  demo: () => request<Job>("/api/jobs/demo", { method: "POST" }),
  upload: (form: FormData) => request<Job>("/api/jobs", { method: "POST", body: form }),
  rerun: (id: string) => request<Job>(`/api/jobs/${enc(id)}/rerun`, { method: "POST" }),
  clusters: (id: string, offset: number, limit = 20) =>
    request<Page<Cluster>>(`/api/jobs/${enc(id)}/clusters?offset=${offset}&limit=${limit}`),
  review: (id: string, priority: "high" | "low" | null, offset: number, limit = 10) => {
    const qs = new URLSearchParams({ offset: String(offset), limit: String(limit) });
    if (priority) qs.set("priority", priority);
    return request<Page<ReviewItem>>(`/api/jobs/${enc(id)}/review?${qs}`);
  },
  decide: (id: string, a: string, b: string, same: boolean) =>
    request<void>(`/api/jobs/${enc(id)}/decisions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ a, b, same }),
    }),
  planUrl: (id: string) => `/api/jobs/${enc(id)}/merge-plan.csv`,
};
