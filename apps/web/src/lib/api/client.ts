import type {
  AgentRunInput,
  AgentTrace,
  AuthUser,
  CoachFocus,
  CoachResult,
  CreateSessionInput,
  Diagnosis,
  GenericReview,
  KnowledgeSearch,
  LoginAccountInput,
  RegisterAccountInput,
  ReviewListing,
  ReviewRunInput,
  SessionResponse,
  StepInput,
  StepVerdict,
  TurnInput,
} from "./types";

// `??` (not `||`) matters: an explicitly empty value means same-origin, which
// is what the nginx deployment relies on. Unset still falls back to local dev.
export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * The server rejected a write because the session changed after it was read.
 * The caller must reload before offering the action again; retrying the same
 * body could apply it on top of a state the user never saw.
 */
export function isSessionConflict(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 409;
}

/**
 * `/auth/me` (or a gated session route) says there is no valid session. The web
 * client never stores a token: the only credential is the HttpOnly cookie, so
 * the fix is always to send the user to `/login`.
 */
export function isUnauthorized(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 401;
}

/**
 * `/auth/me` answers 403 only when this deployment runs with `SYNAPSE_AUTH=off`.
 * That is not a failed login: there is no account layer at all, so the UI must
 * render no prompt and leave the local single-user flow untouched.
 */
export function isAuthDisabled(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 403;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      // The session cookie is HttpOnly and SameSite=Lax. Sending it on every
      // call keeps the API useful behind nginx (API_BASE = "") as well as in
      // the local split (web :3000, api :8000, same site "localhost").
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
    });
  } catch {
    throw new ApiError(
      0,
      `连不上诊断服务（${API_BASE}），请确认 FastAPI 已启动。`,
    );
  }

  // 204/205 have no body by definition; parsing "" would still work, but the
  // explicit branch keeps `logoutAccount` (and any future DELETE) honest.
  if (response.status === 204 || response.status === 205) {
    return undefined as T;
  }

  const text = await response.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }

  if (!response.ok) {
    const detail =
      body &&
      typeof body === "object" &&
      "detail" in body &&
      typeof body.detail === "string"
        ? body.detail
        : `请求失败（HTTP ${response.status}）`;
    throw new ApiError(response.status, detail);
  }
  return body as T;
}

/** The account behind the session cookie; 401 logged out, 403 auth disabled. */
export function getMe(): Promise<AuthUser> {
  return request<AuthUser>("/api/v1/auth/me");
}

/** Create the first owner account; 409 when registration is closed. */
export function registerAccount(input: RegisterAccountInput): Promise<AuthUser> {
  return request<AuthUser>("/api/v1/auth/register", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

/** Exchange email/password for a new HttpOnly cookie. */
export function loginAccount(input: LoginAccountInput): Promise<AuthUser> {
  return request<AuthUser>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

/**
 * Revoke the server-side session and clear the cookie. Idempotent and safe to
 * call without a session; the response carries no account data.
 */
export async function logoutAccount(): Promise<void> {
  await request<null>("/api/v1/auth/logout", { method: "POST" });
}

export function createSession(input: CreateSessionInput): Promise<SessionResponse> {
  return request<SessionResponse>("/api/v1/sessions", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getSession(sessionId: string): Promise<SessionResponse> {
  return request<SessionResponse>(`/api/v1/sessions/${encodeURIComponent(sessionId)}`);
}

export function submitTurn(
  sessionId: string,
  input: TurnInput,
): Promise<SessionResponse> {
  return request<SessionResponse>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/turns`,
    { method: "POST", body: JSON.stringify(input) },
  );
}

/**
 * Append the intake's one clarification. The session stays closed: this only
 * updates what the intake derives from the student's words.
 */
export function answerClarifier(
  sessionId: string,
  answer: string,
): Promise<SessionResponse> {
  return request<SessionResponse>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/intake`,
    { method: "POST", body: JSON.stringify({ answer }) },
  );
}

/**
 * Append one answer to the intake's current structural follow-up. The session
 * stays closed; this only re-derives the coverage view from the local text.
 */
export function answerProbe(
  sessionId: string,
  answer: string,
): Promise<SessionResponse> {
  return request<SessionResponse>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/intake/probe`,
    { method: "POST", body: JSON.stringify({ answer }) },
  );
}

/**
 * Read the bounded tool trace for a generic intake. Read-only: no code runs,
 * no session state changes, and the answer store is not read.
 */
export function getAgentTrace(sessionId: string): Promise<AgentTrace> {
  return request<AgentTrace>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/agent`,
  );
}

/**
 * Run one explicitly pasted Python reproduction and return the same trace
 * shape. Only an executable framework accepts this; with `SYNAPSE_EXEC=off`
 * the trace records a skipped step instead of a fake pass.
 */
export function runAgentTrace(
  sessionId: string,
  input: AgentRunInput,
): Promise<AgentTrace> {
  return request<AgentTrace>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/agent/run`,
    { method: "POST", body: JSON.stringify(input) },
  );
}

/**
 * Run one explicitly pasted Python reproduction and return a code review card.
 * Only an executable session accepts this (409 otherwise); with
 * `SYNAPSE_EXEC=off` the card records `skipped` instead of a fake run. The
 * session is not modified and the answer store is not read.
 */
export function runReview(
  sessionId: string,
  input: ReviewRunInput,
): Promise<GenericReview> {
  return request<GenericReview>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/review/run`,
    { method: "POST", body: JSON.stringify(input) },
  );
}

/** Verify one step; read-only, so it never advances the dialogue. */
export function verifyStep(
  sessionId: string,
  input: StepInput,
): Promise<StepVerdict> {
  return request<StepVerdict>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/steps`,
    { method: "POST", body: JSON.stringify(input) },
  );
}

export function exitSession(
  sessionId: string,
  reveal = false,
): Promise<SessionResponse> {
  return request<SessionResponse>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/exit`,
    {
      method: "POST",
      body: JSON.stringify({ reveal }),
    },
  );
}

/** Record the student's disagreement; the diagnosis itself is not changed. */
export function disagreeWithCard(sessionId: string): Promise<Diagnosis> {
  return request<Diagnosis>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/card/disagree`,
    { method: "POST" },
  );
}

/** Read the local review queue; the teacher page never writes back. */
export function listReviewItems(): Promise<ReviewListing> {
  return request<ReviewListing>("/api/v1/review/items");
}

/**
 * Ask the process coach "where am I wrong" or "how do I start".
 *
 * Read-only: it does not advance the session and never reads the answer store.
 * With no model configured the answer is the deterministic `规则版`; a model
 * failure is already converted into the rule result server-side.
 */
export function requestCoach(
  sessionId: string,
  focus: CoachFocus,
): Promise<CoachResult> {
  return request<CoachResult>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/coach`,
    { method: "POST", body: JSON.stringify({ focus }) },
  );
}

/**
 * Look up sourced knowledge cards for a concept label. Read-only: it never
 * advances the session. The query must be a label, not the student's prose.
 */
export interface KnowledgeSearchOptions {
  subject?: string;
  verification?: string;
  limit?: number;
}

export function searchKnowledge(
  query: string,
  options: KnowledgeSearchOptions = {},
): Promise<KnowledgeSearch> {
  const params = new URLSearchParams({
    q: query,
    limit: String(options.limit ?? 3),
  });
  if (options.subject) params.set("subject", options.subject);
  if (options.verification) params.set("verification", options.verification);
  return request<KnowledgeSearch>(`/api/v1/knowledge/search?${params.toString()}`);
}