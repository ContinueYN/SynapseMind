/**
 * Public API barrel.
 *
 * Pages and components may import this barrel or a narrow feature module
 * (`@/src/lib/api/sessions`, `@/src/lib/api/auth`, ...). The shared transport
 * and ticket-bootstrap queue live in `./http` and are intentionally not
 * re-exported here. Wire types stay in `./types`; `./generated` stays generated.
 */

export {
  API_BASE,
  ApiError,
  isAuthDisabled,
  isSessionConflict,
  isSessionReused,
  isUnauthorized,
  SESSION_REUSED_EVENT,
} from "./http";
export {
  getMe,
  loginAccount,
  logoutAccount,
  registerAccount,
} from "./auth";
export {
  deleteModelSettings,
  getModelSettings,
  saveModelSettings,
  testModelSettings,
} from "./settings";
export {
  answerClarifier,
  answerProbe,
  createSession,
  disagreeWithCard,
  exitSession,
  getSession,
  submitTurn,
} from "./sessions";
export { verifyStep } from "./steps";
export { getAgentTrace, runAgentTrace } from "./agent";
export { requestCoach } from "./coach";
export { listReviewItems, runReview } from "./review";
export { searchKnowledge } from "./knowledge";
export type { KnowledgeSearchOptions } from "./knowledge";