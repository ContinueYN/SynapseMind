import type { components } from "./generated";

/**
 * Response contracts are generated from the FastAPI OpenAPI document:
 *   python scripts/contracts/generate.py
 *
 * Only the request input stays hand-written, because the browser intentionally
 * relies on server defaults (`locale`, `mode`, empty work strings).
 */
type Schemas = components["schemas"];

export type SessionResponse = Schemas["SessionOut"];
export type Probe = Schemas["ProbeOut"];
export type Diagnosis = Schemas["DiagnosisOut"];
export type DiagnosisCard = Schemas["CardOut"];
export type StructureHint = Schemas["HintOut"];
export type HintStep = Schemas["HintStepOut"];
export type Scaffold = Schemas["ScaffoldOut"];
export type ScaffoldStep = Schemas["ScaffoldStepOut"];
export type HistoryItem = Schemas["HistoryItemOut"];
export type Progress = Schemas["ProgressOut"];
export type TurnInput = Schemas["TurnRequest"];
export type StepInput = Schemas["StepRequest"];
export type StepVerdict = Schemas["StepVerdictOut"];
export type ReviewItem = Schemas["ReviewItemOut"];
export type ReviewListing = Schemas["ReviewItemsOut"];
export type KnowledgeHit = Schemas["KnowledgeHitOut"];
export type KnowledgeSearch = Schemas["KnowledgeSearchOut"];
export type Domain = Schemas["DomainOut"];
export type DomainIntake = Schemas["DomainIntakeOut"];
export type GenericReview = Schemas["GenericReviewOut"];
export type GenericReviewFinding = NonNullable<GenericReview["findings"]>[number];
export type GenericReviewEvidence = NonNullable<GenericReview["evidence"]>[number];
export type GenericReviewOption = NonNullable<GenericReview["options"]>[number];
export type AgentTrace = Schemas["AgentTraceOut"];
export type AgentStep = Schemas["AgentStepOut"];
export type AgentSuggestion = Schemas["AgentSuggestionOut"];
/** Process coach: feedback on the attempt/process, never a solution. */
export type CoachResult = Schemas["CoachOut"];
export type CoachPoint = Schemas["CoachPointOut"];
export type CoachFocus = CoachResult["focus"];
export type VerificationMode = Domain["verification"];

/**
 * The public account view from `/api/v1/auth/me` (and the register/login
 * responses). Hand-written because the generated contract file predates the
 * auth slice; the fields mirror `AuthUserOut` and never include the password
 * digest or the session token.
 */
export interface AuthUser {
  id: string;
  email: string;
  display_name: string | null;
  created_at: string;
}

export interface RegisterAccountInput {
  email: string;
  password: string;
  display_name?: string;
}

export interface LoginAccountInput {
  email: string;
  password: string;
}

export interface AgentRunInput {
  code: string;
  tests?: string;
}

/** Explicit code for one reproduction card; a blank `tests` means "none". */
export interface ReviewRunInput {
  code: string;
  tests?: string;
}

export type SessionState =
  | "INGEST"
  | "PARSE"
  | "NEED_INPUT"
  | "ALIGN"
  | "PROBE"
  | "SCAFFOLD"
  | "DIAGNOSE"
  | "INTERVENE"
  | "VERIFY"
  | "STOP"
  | "CLOSED";

export interface CreateSessionInput {
  problem: {
    text: string;
    /** 开放领域标签：省略即自动判断，不限于已知学科。 */
    subject?: string;
    grade?: "high_school";
  };
  attempt: {
    answer: string;
    work?: string;
    stuck_at?: string;
    confidence?: number;
    self_report?: "no_idea" | "wrong" | "unsure" | "correct_but_guessed";
  };
  locale?: "zh-CN" | "en";
  mode?: "learning";
}