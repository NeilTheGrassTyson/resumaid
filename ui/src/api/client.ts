/**
 * Typed API client. All shapes come from types.ts, which is generated from the FastAPI
 * OpenAPI schema — so the SPA's types are never maintained by hand (ADR 0002).
 */
import type { components } from "./types";

export type QueueEntry = components["schemas"]["QueueEntryOut"];
export type Slate = components["schemas"]["SlateOut"];
export type Application = components["schemas"]["ApplicationOut"];
export type RunOut = components["schemas"]["RunOut"];
export type Stats = components["schemas"]["StatsOut"];
export type Resume = components["schemas"]["ResumeOut"];
export type Profile = components["schemas"]["Profile"];
export type Interests = components["schemas"]["Interests"];
export type PlacePref = components["schemas"]["PlacePref"];
export type RoleFamily = components["schemas"]["RoleFamily"];

export type SetupStatus = {
  resumes: number;
  role_families: number;
  boards: number;
  ready: boolean;
};

export type Board = {
  id: number;
  source: string;
  token: string;
  company: string | null;
  discovered_via: string | null;
  last_polled_at: string | null;
  last_status: string | null;
  enabled: number;
};
export type RejectionReason = components["schemas"]["RejectionReason"];
export type Outcome = components["schemas"]["Outcome"];

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* keep the status text */
    }
    throw new ApiError(response.status, detail);
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) });

const put = <T>(path: string, body: unknown) =>
  request<T>(path, {
    method: "PUT",
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json" },
  });

export const api = {
  slate: () => request<Slate>("/api/queue"),
  filtered: () => request<QueueEntry[]>("/api/queue/filtered"),
  ready: () => request<QueueEntry[]>("/api/queue/ready"),
  approve: (id: number, note?: string) =>
    post<QueueEntry>(`/api/queue/${id}/approve`, { note: note ?? null }),
  reject: (id: number, reason: RejectionReason, note?: string) =>
    post<QueueEntry>(`/api/queue/${id}/reject`, { reason, note: note ?? null }),
  snooze: (id: number, days: number) => post<QueueEntry>(`/api/queue/${id}/snooze`, { days }),
  unapprove: (id: number) => post<QueueEntry>(`/api/queue/${id}/unapprove`),
  paste: (id: number, text: string) => post<QueueEntry>(`/api/queue/${id}/paste`, { text }),
  /** Records that the human already submitted. Never initiates one. */
  markSubmitted: (id: number, channel?: string) =>
    post<QueueEntry>(`/api/queue/${id}/submitted`, { channel: channel ?? null }),
  applications: () => request<Application[]>("/api/applications"),
  updateApplication: (id: number, patch: Record<string, unknown>) =>
    request<Application>(`/api/applications/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
      headers: { "Content-Type": "application/json" },
    }),
  stats: () => request<Stats>("/api/applications/stats"),
  run: () => post<RunOut>("/api/run"),

  // --- setup ----------------------------------------------------------------
  setupStatus: () => request<SetupStatus>("/api/setup/status"),
  resumes: () => request<Resume[]>("/api/resumes"),

  /** Multipart upload. No Content-Type header — the browser sets the boundary. */
  uploadResume: async (file: File, isMaster: boolean): Promise<Resume> => {
    const body = new FormData();
    body.append("file", file);
    const response = await fetch(`/api/resumes?is_master=${isMaster}`, { method: "POST", body });
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const parsed = await response.json();
        if (typeof parsed?.detail === "string") detail = parsed.detail;
      } catch {
        /* keep the status text */
      }
      throw new ApiError(response.status, detail);
    }
    return (await response.json()) as Resume;
  },

  deleteResume: (id: number) => request<void>(`/api/resumes/${id}`, { method: "DELETE" }),
  setMasterResume: (id: number) => post<Resume>(`/api/resumes/${id}/master`),

  profile: () => request<Profile>("/api/profile"),
  saveProfile: (profile: Profile) => put<Profile>("/api/profile", profile),
  reparseProfile: () => post<Profile>("/api/profile/reparse"),

  interests: () => request<Interests>("/api/interests"),
  saveInterests: (interests: Interests) => put<Interests>("/api/interests", interests),

  boards: () => request<Board[]>("/api/boards"),
  addBoard: (url: string) =>
    post<{ source: string; token: string; added: boolean }>("/api/boards", { url }),
  removeBoard: (id: number) => request<void>(`/api/boards/${id}`, { method: "DELETE" }),
  enableBoard: (id: number) => post<void>(`/api/boards/${id}/enable`),
};

export const REJECTION_REASONS: { value: RejectionReason; label: string }[] = [
  { value: "wrong_seniority", label: "Wrong seniority" },
  { value: "wrong_location", label: "Wrong location" },
  { value: "wrong_industry", label: "Wrong industry" },
  { value: "not_this_company", label: "Not this company" },
  { value: "already_applied", label: "Already applied" },
  { value: "stale_posting", label: "Stale posting" },
  { value: "compensation", label: "Compensation" },
  { value: "other", label: "Other" },
];

export const OUTCOMES: Outcome[] = [
  "pending", "oa", "interview", "offer", "rejected", "ghosted", "withdrawn",
];
