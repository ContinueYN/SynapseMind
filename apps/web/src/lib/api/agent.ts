/**
 * Agent tool trace endpoints. Read-only: no code runs unless the caller
 * explicitly submits it, and the answer store is never read.
 */

import type { AgentRunInput, AgentTrace } from "./types";
import { request } from "./http";

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