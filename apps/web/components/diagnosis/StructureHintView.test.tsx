import type { ReactNode } from "react";

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { StructureHintView } from "./StructureHintView";
import type { StructureHint } from "@/src/lib/api/types";

// `next/link` expects an App Router context. The hint view only needs an anchor,
// so the test substitutes one instead of mounting the Next runtime.
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

function hint(overrides: Partial<StructureHint> = {}): StructureHint {
  return {
    version: "0.2",
    session_id: "S_ABC123456789",
    problem_id: "P_GEN_ABC123",
    subject: "chinese",
    level: "none",
    one_line: "这道题拆成 3 步；你的过程里看起来只写到了「定位原文」的一部分。",
    steps: [
      { node_id: "n1", text: "读题干，圈出限制语", status: "covered" },
      { node_id: "n2", text: "定位原文，勾出依据句", status: "partial" },
      { node_id: "n3", text: "分点作答，写完整句子", status: "missing" },
    ],
    focus_node_id: "n2",
    next_step: "先把「定位原文，勾出依据句」补全，再回来按结构自查。",
    disclaimer: "该学科没有可自动验证的标准答案：这里只判断有没有写到，不判断对错。",
    ...overrides,
  };
}

describe("StructureHintView", () => {
  it("counts covered and partial as touched, and keeps a separate partial label", () => {
    render(<StructureHintView hint={hint()} sessionId="S_ABC123456789" />);

    expect(screen.getByLabelText("3 步中有 2 步写到或写到了一部分")).toBeInTheDocument();
    expect(screen.getByText("已写到")).toBeInTheDocument();
    expect(screen.getByText("写到了一部分")).toBeInTheDocument();
    expect(screen.getByText("没看到")).toBeInTheDocument();
    expect(screen.getByText("下一步先看「定位原文，勾出依据句」")).toBeInTheDocument();
    expect(screen.getByText(hint().disclaimer)).toBeInTheDocument();
  });

  it("marks the focus step and leaves the rest unfocused", () => {
    render(<StructureHintView hint={hint()} sessionId="S_ABC123456789" />);

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[1]).toHaveAttribute("data-focus", "true");
    expect(items[1]).toHaveAttribute("data-status", "partial");
    expect(items[0]).not.toHaveAttribute("data-focus");
  });

  it("says every step was mentioned when nothing is missing", () => {
    render(
      <StructureHintView
        hint={hint({
          steps: (hint().steps ?? []).map((step) => ({
            ...step,
            status: "covered" as const,
          })),
          focus_node_id: null,
          one_line: "这道题拆成 3 步；你的过程里每一步都提到了。",
          next_step: "按顺序对照这些步骤，确认每一步的结论都成立。",
        })}
        sessionId="S_ABC123456789"
      />,
    );

    expect(screen.getByText("每一步都提到了")).toBeInTheDocument();
    expect(screen.queryByText("下一步先看", { exact: false })).not.toBeInTheDocument();
    expect(screen.getByLabelText("3 步中有 3 步写到或写到了一部分")).toBeInTheDocument();
  });

  it("does not turn a partial step into a correctness claim", () => {
    render(<StructureHintView hint={hint()} sessionId="S_ABC123456789" />);

    expect(screen.queryByText(/你错了|这一步错了|理解偏了/)).not.toBeInTheDocument();
  });
});