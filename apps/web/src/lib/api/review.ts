/**
 * Generic review endpoints: the code reproduction card, and the internal
 * disagreement review queue.
 */

import type { GenericReview, ReviewListing, ReviewRunInput } from "./types";
import { request } from "./http";

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

/**
 * Read the local review queue; the internal review page never writes back.
 * When account auth is enabled this route is gated and answers 401 without a
 * session cookie.
 */
export function listReviewItems(): Promise<ReviewListing> {
  return request<ReviewListing>("/api/v1/review/items");
}