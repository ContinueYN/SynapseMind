import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DiagnosisCardView } from "./DiagnosisCardView";
import { ApiError } from "@/src/lib/api/http";
import { disagreeWithCard } from "@/src/lib/api/sessions";
import type { DiagnosisCard } from "@/src/lib/api/types";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/src/lib/api/sessions", () => ({
  disagreeWithCard: vi.fn(),
}));

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

const ATTRIBUTION: NonNullable<DiagnosisCard["attribution"]> = {
  dimensions: [
    { key: "Gf", label: "流体推理", weight: 0.7 },
    { key: "WM", label: "工作记忆", weight: 0.5 },
  ],
  all_dimensions: [
    { key: "V", label: "言语理解", weight: 0 },
    { key: "Gf", label: "流体推理", weight: 0.7 },
    { key: "Gv", label: "视觉空间", weight: 0 },
    { key: "WM", label: "工作记忆", weight: 0.5 },
    { key: "Gs", label: "加工速度", weight: 0 },
    { key: "LTS", label: "长时存取", weight: 0 },
    { key: "M", label: "元认知", weight: 0.4 },
  ],
  note: "题目需求标签，不是能力测评；单题不足以断言。",
};

const CHC_LABELS = [
  "言语理解",
  "流体推理",
  "视觉空间",
  "工作记忆",
  "加工速度",
  "长时存取",
  "元认知",
] as const;

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

  it("hides the CHC block when the card has no attribution", () => {
    const { container } = render(
      <DiagnosisCardView card={CARD} sessionId="S_ABC123456789" />,
    );

    expect(screen.queryByText("认知需求画像")).not.toBeInTheDocument();
    expect(container.querySelector(".sm-attr")).toBeNull();
  });

  it("renders all seven CHC demand dimensions with weights and top rows", () => {
    const { container } = render(
      <DiagnosisCardView
        card={{ ...CARD, attribution: ATTRIBUTION }}
        sessionId="S_ABC123456789"
      />,
    );

    expect(
      screen.getByRole("heading", { name: "认知需求画像" }),
    ).toBeInTheDocument();
    expect(screen.getByText("CHC 七维 · 本题节点")).toBeInTheDocument();

    for (const label of CHC_LABELS) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }

    const rows = container.querySelectorAll<HTMLElement>(".sm-attr-row");
    expect(rows).toHaveLength(7);
    expect(container.querySelectorAll(".sm-attr-bar")).toHaveLength(7);
    expect(container.querySelectorAll(".sm-attr-row--top")).toHaveLength(2);
    expect(rows[1]).toHaveClass("sm-attr-row--top");
    expect(rows[3]).toHaveClass("sm-attr-row--top");
    expect(rows[0]).not.toHaveClass("sm-attr-row--top");

    expect(within(rows[1]).getByText("0.70")).toBeInTheDocument();
    expect(
      within(rows[1]).getByRole("img", {
        name: "流体推理（Gf）本题需求权重 0.70",
      }),
    ).toBeInTheDocument();
    expect(
      within(rows[3]).getByText("主要需求"),
    ).toBeInTheDocument();

    expect(screen.getByText(ATTRIBUTION.note)).toBeInTheDocument();
    expect(
      screen.getByText(
        "条长是本题节点的需求权重（0–1），未标注维度记 0；不是对你的测评，单题不足以断言任何一项能力。",
      ),
    ).toBeInTheDocument();

    expect(container.textContent).not.toMatch(/IQ|能力分|排名|智商|百分位/);
  });

  it("falls back to the supplied dimensions when all_dimensions is absent", () => {
    const { container } = render(
      <DiagnosisCardView
        card={{
          ...CARD,
          attribution: {
            dimensions: ATTRIBUTION.dimensions,
            note: ATTRIBUTION.note,
          },
        }}
        sessionId="S_ABC123456789"
      />,
    );

    expect(
      screen.getByRole("heading", { name: "认知需求画像" }),
    ).toBeInTheDocument();
    expect(screen.getByText("本题节点需求")).toBeInTheDocument();
    expect(container.querySelectorAll(".sm-attr-row")).toHaveLength(2);
    expect(container.querySelectorAll(".sm-attr-row--top")).toHaveLength(2);
    expect(screen.queryByText("视觉空间")).not.toBeInTheDocument();
    expect(container.textContent).not.toMatch(/IQ|能力分|排名|智商|百分位/);
  });
});