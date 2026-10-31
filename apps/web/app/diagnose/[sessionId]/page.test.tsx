import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DiagnosePage from "./page";
import { ApiError, exitSession, getSession, submitTurn } from "@/src/lib/api/client";
import type { SessionResponse } from "@/src/lib/api/types";

vi.mock("next/navigation", () => ({
  useParams: () => ({ sessionId: "S_CONFLICT" }),
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/src/lib/session-handoff", () => ({
  adoptSession: () => null,
}));

vi.mock("@/src/lib/api/client", () => {
  class ApiError extends Error {
    readonly status: number;

    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  }
  return {
    ApiError,
    API_BASE: "http://localhost:8000",
    getSession: vi.fn(),
    submitTurn: vi.fn(),
    exitSession: vi.fn(),
    searchKnowledge: vi.fn().mockResolvedValue({
      version: "0.1",
      enabled: false,
      query: "",
      hits: [],
    }),
    isSessionConflict: (error: unknown) =>
      error instanceof ApiError && error.status === 409,
  };
});

const FIRST: SessionResponse = {
  session_id: "S_CONFLICT",
  state: "PROBE",
  problem_id: "P_E2E_MATH",
  problem_title: "解方程",
  problem_text: "解方程 x+1=2x。",
  subject: "math",
  mode: "learning",
  turn: 0,
  max_turns: 6,
  prompt: {
    action: "ask",
    question: "第一问：先移项还是先合并？",
    options: ["先移项", "先合并同类项"],
    hint_level: 0,
    reason_code: "DISCRIMINATE_HYPOTHESIS",
    confidence: 0.45,
  },
  diagnosis: null,
  hint: null,
  notice: null,
  progress: {
    turn: 0,
    max_turns: 6,
    confidence: 0.45,
    top_hypothesis: "H_L1",
  },
  history: [],
};

const LATEST: SessionResponse = {
  ...FIRST,
  turn: 1,
  prompt: {
    action: "confirm",
    question: "第二问：合并同类项之后呢？",
    options: ["两边同时减去 x", "直接除以 x"],
    hint_level: 0,
    reason_code: "CONFIRM_HYPOTHESIS",
    confidence: 0.62,
  },
  progress: {
    ...FIRST.progress,
    turn: 1,
    confidence: 0.62,
  },
  history: [
    {
      turn: 1,
      question: "第一问：先移项还是先合并？",
      answer: "先移项",
      option_id: "A",
      action: "answer",
      is_unknown: false,
    },
  ],
};

const CLOSED: SessionResponse = {
  ...FIRST,
  state: "CLOSED",
  prompt: null,
  notice: "已退出学习模式；本次不生成卡点卡，也不展示最终答案。",
};

describe("DiagnosePage conflict recovery", () => {
  beforeEach(() => {
    vi.mocked(getSession).mockReset();
    vi.mocked(submitTurn).mockReset();
    vi.mocked(exitSession).mockReset();
    Element.prototype.scrollIntoView = vi.fn();
  });

  it("reloads the latest state instead of replaying a stale answer", async () => {
    vi.mocked(getSession)
      .mockResolvedValueOnce(FIRST)
      .mockResolvedValueOnce(LATEST);
    vi.mocked(submitTurn).mockRejectedValueOnce(
      new ApiError(409, "stale revision"),
    );

    const user = userEvent.setup();
    render(<DiagnosePage />);

    await screen.findByText("第一问：先移项还是先合并？");
    await user.click(screen.getByRole("button", { name: /先移项/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "已刷新到最新状态",
    );
    expect(screen.getByText("第二问：合并同类项之后呢？")).toBeInTheDocument();
    expect(submitTurn).toHaveBeenCalledTimes(1);
  });

  it("reveals the stored solution only after a second explicit click", async () => {
    vi.mocked(getSession).mockResolvedValueOnce(CLOSED);
    vi.mocked(exitSession).mockResolvedValueOnce({
      ...CLOSED,
      answer: "a∈[1/e,+∞)",
      solution: "定义域 x>0。分 a≤0 与 a>0 讨论。",
    });

    const user = userEvent.setup();
    render(<DiagnosePage />);

    const button = await screen.findByRole("button", { name: "看完整解法" });
    expect(exitSession).not.toHaveBeenCalled();

    await user.click(button);
    expect(screen.getByRole("button", { name: /再点一次/ })).toBeInTheDocument();
    expect(exitSession).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /再点一次/ }));

    expect(exitSession).toHaveBeenCalledWith("S_CONFLICT", true);
    expect(await screen.findByText("a∈[1/e,+∞)")).toBeInTheDocument();
    expect(screen.getByText(/定义域 x>0/)).toBeInTheDocument();
  });
});