/**
 * Sourced knowledge-card lookup. Read-only: it never advances the session, and
 * the query must be a concept label rather than the student's prose.
 */

import type { KnowledgeSearch } from "./types";
import { request } from "./http";

export interface KnowledgeSearchOptions {
  subject?: string;
  verification?: string;
  limit?: number;
}

/**
 * Look up sourced knowledge cards for a concept label. Read-only: it never
 * advances the session. The query must be a label, not the student's prose.
 */
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