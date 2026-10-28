export type SessionState =
  | "INGEST"
  | "PARSE"
  | "NEED_INPUT"
  | "ALIGN"
  | "PROBE"
  | "DIAGNOSE"
  | "INTERVENE"
  | "VERIFY"
  | "STOP"
  | "CLOSED";

export type Action = "ask" | "hint" | "confirm";

export interface Probe {
  action: Action;
  question: string;
  options: string[];
  hint_level: number;
  reason_code: string;
  confidence: number;
}

export interface Progress {
  turn: number;
  max_turns: number;
  confidence: number;
  top_hypothesis: string;
}

export interface HistoryItem {
  turn: number;
  question: string;
  answer: string;
  option_id: string | null;
  action: string;
  is_unknown: boolean;
}

export interface DiagnosisCard {
  layer: "L0" | "L1" | "L2" | "L3" | "L4" | "L5" | "L6";
  label: string;
  node_id: string;
  one_line: string;
  evidence: string[];
  excluded: string[];
  confidence: number;
  confidence_label: "high" | "medium" | "low";
  next_action: {
    type: "micro_lesson" | "worked_example" | "probe_more" | "none";
    concept_id?: string;
    duration_min?: number;
    task_id?: string;
  };
  verify: {
    type: "transfer" | "none";
    due_hours: number;
    item_id?: string;
  };
  disagree: boolean;
}

export interface Diagnosis {
  version: "0.1";
  session_id: string;
  problem_id: string;
  card: DiagnosisCard;
}

export interface SessionResponse {
  session_id: string;
  state: SessionState;
  problem_id: string;
  problem_title: string;
  mode: string;
  turn: number;
  max_turns: number;
  prompt: Probe | null;
  diagnosis: Diagnosis | null;
  notice: string | null;
  progress: Progress;
  history: HistoryItem[];
}

export interface CreateSessionInput {
  problem: {
    text: string;
    subject?: "math";
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

export interface TurnInput {
  answer: string;
  option_id?: string;
}