import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, requestCoach } from "@/src/lib/api/client";
import type { CoachResult } from "@/src/lib/api/types";

import { CoachPanel } from "./CoachPanel";

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
    requestCoach: vi.fn(),
    isUnauthorized: (error: unknown) =>
      error instanceof ApiError && error.status === 401,
  };
});

const RULES: CoachResult = {
  version: "0.1",
  mode: "rules",
  focus: "where_wrong",
  headline: "先不判对错：可以从你写的这段过程里核对两处。",
  points: [
    {
      kind: "process_note",
      text: "你写到「手机能查资料」。可以先核对：这一步用到的依据有没有写出来。",
      basis: "attempt.quote",
    },
    {
      kind: "next_step",
      text: "把「已知 → 依据 → 结果」三行分开写。",
      basis: "checklist[0]",
    },
  ],
  next_question: "这一步用到的依据，能在题目里找到对应条件吗？",
  not_claimed: ["没有判断这段过程或答案的对错。", "没有给出解法、评分或排名。"],
  disclaimer: "规则版：按固定规则取证据，没有调用模型；这是过程反馈，不是解法。",
};

const LLM: CoachResult = {
  ...RULES,
  mode: "llm",
  focus: "how_to_start",
  headline: "先不找错：按下面三句把问题搭起来。",
  points: [
    {
      kind: "next_step",
      text: "先写一句结论：你想让读者接受什么。",
      basis: "llm:intake",
    },
    {
      kind: "next_step",
      text: "再补一句证据：哪些事实在支撑它。",
      basis: "llm:problem",
    },
  ],
  disclaimer: "模型版：措辞由模型整理，依据只来自题面和你的作答；不判断对错。",
};

describe("CoachPanel", () => {
  beforeEach(() => {
    vi.mocked(requestCoach).mockReset();
  });

  it("offers both asks and sends the matching focus", async () => {
    vi.mocked(requestCoach)
      .mockResolvedValueOnce(RULES)
      .mockResolvedValueOnce(LLM);
    const user = userEvent.setup();

    render(<CoachPanel sessionId="S_COACH" />);

    await user.click(screen.getByRole("button", { name: "我错在哪" }));
    expect(await screen.findByText(RULES.headline)).toBeInTheDocument();
    expect(requestCoach).toHaveBeenNthCalledWith(1, "S_COACH", "where_wrong");

    await user.click(screen.getByRole("button", { name: "怎么开始" }));
    expect(await screen.findByText(LLM.headline)).toBeInTheDocument();
    expect(requestCoach).toHaveBeenNthCalledWith(2, "S_COACH", "how_to_start");
  });

  it("shows a loading state and disables both actions while asking", async () => {
    let resolve!: (value: CoachResult) => void;
    vi.mocked(requestCoach).mockReturnValue(
      new Promise<CoachResult>((done) => {
        resolve = done;
      }),
    );
    const user = userEvent.setup();

    render(<CoachPanel sessionId="S_COACH" />);
    await user.click(screen.getByRole("button", { name: "我错在哪" }));

    expect(screen.getByText("正在整理过程反馈……")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "正在整理……" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "怎么开始" })).toBeDisabled();

    resolve(RULES);
    expect(await screen.findByText(RULES.headline)).toBeInTheDocument();
    expect(screen.queryByText("正在整理过程反馈……")).not.toBeInTheDocument();
  });

  it("renders the honest rules label, the next question and not_claimed", async () => {
    vi.mocked(requestCoach).mockResolvedValue(RULES);
    const user = userEvent.setup();

    render(<CoachPanel sessionId="S_COACH" />);
    await user.click(screen.getByRole("button", { name: "我错在哪" }));

    expect((await screen.findAllByText("规则版")).length).toBeGreaterThan(0);
    expect(screen.getByText("下一个问题：")).toBeInTheDocument();
    expect(screen.getByText(RULES.next_question)).toBeInTheDocument();
    expect(screen.getByText("这次没有判断")).toBeInTheDocument();
    for (const item of RULES.not_claimed) {
      expect(screen.getByText(item)).toBeInTheDocument();
    }
    expect(screen.queryByText("模型版")).not.toBeInTheDocument();
  });

  it("labels a model result as 模型版, not as a diagnosis", async () => {
    vi.mocked(requestCoach).mockResolvedValue(LLM);
    const user = userEvent.setup();

    render(<CoachPanel sessionId="S_COACH" />);
    await user.click(screen.getByRole("button", { name: "怎么开始" }));

    expect((await screen.findAllByText("模型版")).length).toBeGreaterThan(0);
    expect(screen.getByText(LLM.disclaimer)).toBeInTheDocument();
  });

  it("uses the existing 请先登录 treatment on 401", async () => {
    vi.mocked(requestCoach).mockRejectedValue(new ApiError(401, "需要先登录。"));
    const user = userEvent.setup();

    render(<CoachPanel next="/diagnose/S_COACH" sessionId="S_COACH" />);
    await user.click(screen.getByRole("button", { name: "我错在哪" }));

    expect(await screen.findByText(/请先登录/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "去登录" })).toHaveAttribute(
      "href",
      "/login?next=%2Fdiagnose%2FS_COACH",
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows a short retry message for other failures", async () => {
    vi.mocked(requestCoach).mockRejectedValue(new ApiError(500, "boom"));
    const user = userEvent.setup();

    render(<CoachPanel sessionId="S_COACH" />);
    await user.click(screen.getByRole("button", { name: "怎么开始" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "这次没拿到过程反馈，请稍后再试。",
    );
  });
});