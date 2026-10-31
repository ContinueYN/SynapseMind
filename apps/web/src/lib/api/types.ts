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
    subject?: "math" | "physics" | "chinese";
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