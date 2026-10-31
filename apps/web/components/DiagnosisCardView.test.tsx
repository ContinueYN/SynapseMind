import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DiagnosisCardView } from "./DiagnosisCardView";
import { ApiError, disagreeWithCard } from "@/src/lib/api/client";
import type { DiagnosisCard } from "@/src/lib/api/types";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
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
    disagreeWithCard: vi.fn(),
    isSessionConflict: (error: unknown) =>
      error instanceof ApiError && error.status === 409,
  };
});

const disagree = vi.mocked(disagreeWithCard);

const CARD: DiagnosisCard = {
  layer: "L2",
  label: "概念不清：恒成立与最值",
  node_id: "n3",
  one_line: "漏掉了 a≤0 这一支。",
  evidence: ["第 2 轮选择了「要单独排除」"],
  excluded: [],
  confidence: 0.86,
  confidence_label: "high",
  next_action: {
    type: "micro_lesson",
    concept_id: "node:n3",
    duration_min: 3,
    task_id: "node:n3",
  },
  verify: { type: "transfer", due_hours: 24, item_id: "verify:P_PUB_002" },
  disagree: false,
};

describe("DiagnosisCardView", () => {
  beforeEach(() => {
    disagree.mockReset();
  });

  it("records the disagreement on the server and keeps the state", async () => {
    disagree.mockResolvedValue({
      version: "0.1",
      session_id: "S_ABC123456789",
      problem_id: "P_PUB_002",
      card: { ...CARD, disagree: true },
    });

    const user = userEvent.setup();
    render(<DiagnosisCardView card={CARD} sessionId="S_ABC123456789" />);

    const button = screen.getByRole("button", { name: "我不同意这个判断" });
    await user.click(button);

    await waitFor(() => expect(button).toHaveTextContent("已记录你的反馈"));
    expect(disagree).toHaveBeenCalledWith("S_ABC123456789");
    expect(button).toBeDisabled();
  });

  it("asks for a refresh when the card changed in another window", async () => {
    disagree.mockRejectedValue(new ApiError(409, "stale revision"));

    const user = userEvent.setup();
    render(<DiagnosisCardView card={CARD} sessionId="S_ABC123456789" />);

    await user.click(screen.getByRole("button", { name: "我不同意这个判断" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("另一个窗口");
    expect(
      screen.getByRole("button", { name: "我不同意这个判断" }),
    ).toBeEnabled();
  });

  it("starts from the persisted flag after a reload", () => {
    render(
      <DiagnosisCardView
        card={{ ...CARD, disagree: true }}
        sessionId="S_ABC123456789"
      />,
    );

    expect(screen.getByRole("button", { name: "已记录你的反馈" })).toBeDisabled();
  });
});