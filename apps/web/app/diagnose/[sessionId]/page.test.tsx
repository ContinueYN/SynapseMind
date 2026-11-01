import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DiagnosePage from "./page";
import {
  answerClarifier,
  ApiError,
  exitSession,
  getSession,
  searchKnowledge,
  submitTurn,
} from "@/src/lib/api/client";
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
    answerClarifier: vi.fn(),
    getSession: vi.fn(),
    submitTurn: vi.fn(),
    exitSession: vi.fn(),
    searchKnowledge: vi.fn().mockResolvedValue({
      version: "0.2",
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
  domain: {
    name: "math",
    label: "数学",
    verification: "formal",
    generic: false,
    confidence: 1,
  },
  intake: null,
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

const GENERIC_DOMAIN = {
  name: "generic",
  label: "通用问题",
  verification: "argumentative" as const,
  generic: true,
  confidence: 0,
};

const GENERIC_INTAKE = {
  version: "0.3" as const,
  domain: GENERIC_DOMAIN,
  one_line: "按「通用问题」处理（论证结构）。没有参考结构，先不判断卡点。",
  checklist: ["目标：这一轮想解决什么", "约束：哪些条件不能动"],
  observed: [],
  gaps: [],
  clarifier: "只问一个：这更像代码问题、决策问题，还是学习/证明题？",
  next_step: "补一句话：卡住的那一步在哪个动作上。",
  disclaimer: "不提供唯一正确答案，也不替代医疗、法律或金融专业建议。",
};

const GENERIC: SessionResponse = {
  ...CLOSED,
  subject: "generic",
  domain: GENERIC_DOMAIN,
  intake: GENERIC_INTAKE,
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

describe("DiagnosePage generic entry", () => {
  beforeEach(() => {
    vi.mocked(getSession).mockReset();
    vi.mocked(submitTurn).mockReset();
    vi.mocked(exitSession).mockReset();
    vi.mocked(answerClarifier).mockReset();
    vi.mocked(searchKnowledge).mockReset();
    vi.mocked(searchKnowledge).mockResolvedValue({
      version: "0.2",
      enabled: false,
      query: "",
      hits: [],
    });
    Element.prototype.scrollIntoView = vi.fn();
  });

  it("shows the intake instead of a probe or a card", async () => {
    vi.mocked(getSession).mockResolvedValueOnce(GENERIC);

    render(<DiagnosePage />);

    expect(await screen.findByText("入口整理 · 不定位卡点")).toBeInTheDocument();
    expect(screen.getByText("这次先按通用问题处理")).toBeInTheDocument();
    expect(screen.getByText(/只问一个/)).toBeInTheDocument();
    expect(screen.getByText(/目标：这一轮想解决什么/)).toBeInTheDocument();
    // No probe, no card, no reveal: there is nothing to answer or reveal.
    expect(
      screen.queryByRole("button", { name: "看完整解法" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/系统把握/)).not.toBeInTheDocument();
    expect(screen.getByText("通用问题（通用）")).toBeInTheDocument();
  });

  it("submits the single clarification and shows the updated intake", async () => {
    vi.mocked(getSession).mockResolvedValueOnce(GENERIC);
    vi.mocked(answerClarifier).mockResolvedValueOnce({
      ...GENERIC,
      notice: "补充已并入入口整理；它仍然只说明你提到了什么，不定位卡点。",
      intake: {
        ...GENERIC_INTAKE,
        clarifier: null,
        observed: ["目标"],
      },
    });

    const user = userEvent.setup();
    render(<DiagnosePage />);

    await screen.findByText("入口整理 · 不定位卡点");
    await user.type(
      screen.getByLabelText("补充一句"),
      "这更像一个生活决策：我要不要换城市工作。",
    );
    await user.click(screen.getByRole("button", { name: /并入入口整理/ }));

    expect(answerClarifier).toHaveBeenCalledWith(
      "S_CONFLICT",
      "这更像一个生活决策：我要不要换城市工作。",
    );
    expect(await screen.findByText(/补充已并入入口整理/)).toBeInTheDocument();
    expect(screen.queryByText(/只问一个/)).not.toBeInTheDocument();
    expect(screen.getByText(/你写的里面看到了：目标/)).toBeInTheDocument();
  });

  it("labels a confident domain without calling it generic", async () => {
    vi.mocked(getSession).mockResolvedValueOnce({
      ...GENERIC,
      subject: "programming",
      domain: {
        name: "programming",
        label: "编程",
        verification: "executable",
        generic: false,
        confidence: 1,
      },
      intake: {
        ...GENERIC_INTAKE,
        domain: {
          name: "programming",
          label: "编程",
          verification: "executable",
          generic: false,
          confidence: 1,
        },
        clarifier: null,
      },
    });

    render(<DiagnosePage />);

    expect(await screen.findByText("按「编程」处理")).toBeInTheDocument();
    expect(screen.getByText(/编程 · 可执行验证/)).toBeInTheDocument();
    expect(screen.queryByText(/只问一个/)).not.toBeInTheDocument();
  });

  it("shows a sourced decision framework on a decision intake", async () => {
    const decision = {
      name: "decision",
      label: "决策",
      verification: "argumentative" as const,
      generic: false,
      confidence: 1,
    };
    vi.mocked(getSession).mockResolvedValueOnce({
      ...GENERIC,
      subject: "decision",
      domain: decision,
      intake: {
        ...GENERIC_INTAKE,
        domain: decision,
        clarifier: null,
      },
    });
    vi.mocked(searchKnowledge).mockResolvedValueOnce({
      version: "0.2",
      enabled: true,
      query: "决策",
      hits: [
        {
          card_id: "K_DECISION_REVERSIBLE",
          kind: "method",
          subject: "decision",
          verifications: ["argumentative"],
          title: "可逆决策先做小实验",
          excerpt: "先找成本最低、能撤回的一步。",
          source: {
            title: "OpenStax Principles of Management",
            url: "https://openstax.org/details/books/principles-management",
            license: "CC BY 4.0",
          },
          score: 0.71,
        },
      ],
    });

    render(<DiagnosePage />);

    expect(
      await screen.findByText("可逆决策先做小实验"),
    ).toBeInTheDocument();
    expect(searchKnowledge).toHaveBeenCalledWith("决策", {
      subject: "decision",
      verification: "argumentative",
    });
  });
});