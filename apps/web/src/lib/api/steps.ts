/**
 * Single-step verification. Read-only: it never advances the dialogue.
 */

import type { StepInput, StepVerdict } from "./types";
import { request } from "./http";

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