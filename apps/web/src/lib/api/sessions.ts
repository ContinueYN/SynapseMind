/**
 * Diagnosis session endpoints: create/read a session, answer its turns, and
 * record a disagreement with a card.
 */

import type {
  CreateSessionInput,
  Diagnosis,
  SessionResponse,
  TurnInput,
} from "./types";
import { request } from "./http";

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