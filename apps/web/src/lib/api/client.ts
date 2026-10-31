import type {
  CreateSessionInput,
  Diagnosis,
  ReviewListing,
  SessionResponse,
  StepInput,
  StepVerdict,
  TurnInput,
} from "./types";

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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
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

export function exitSession(sessionId: string): Promise<SessionResponse> {
  return request<SessionResponse>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/exit`,
    { method: "POST" },
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