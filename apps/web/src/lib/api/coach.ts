/**
 * Process coach endpoint. Read-only: it never advances the session and never
 * reads the answer store.
 */

import type { CoachFocus, CoachResult } from "./types";
import { request } from "./http";

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