import type { ReactNode } from "react";

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ScaffoldView } from "./ScaffoldView";
import type { Scaffold } from "@/src/lib/api/types";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

function scaffold(): Scaffold {
  return {
    steps: [
      { label: "第 1 步", node_id: "n1", text: "确认定义域 x>0。" },
      { label: "第 2 步", node_id: "n2", text: "恒成立转最值。" },
    ],
    focus_node_id: "n3",
    next_step: "照着上面的写法，把你的下一行过程写出来；不用写最终答案。",
    disclaimer: "示例只展示起步，不是本题答案；写出一行后继续诊断。",
  };
}

describe("ScaffoldView", () => {
  it("shows the example and the disclaimer without a final answer", () => {
    render(
      <ScaffoldView
        busy={false}
        onSubmit={vi.fn()}
        scaffold={scaffold()}
        sessionId="S_SCAFFOLD"
      />,
    );

    expect(screen.getByText("确认定义域 x>0。")).toBeInTheDocument();
    expect(screen.getByText("恒成立转最值。")).toBeInTheDocument();
    expect(screen.getByText(scaffold().disclaimer)).toBeInTheDocument();
    expect(screen.queryByText(/1\/e/)).not.toBeInTheDocument();
  });

  it("submits the written line and trims it", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <ScaffoldView
        busy={false}
        onSubmit={onSubmit}
        scaffold={scaffold()}
        sessionId="S_SCAFFOLD"
      />,
    );

    const button = screen.getByRole("button", { name: /写好了，继续诊断/ });
    expect(button).toBeDisabled();

    await user.type(screen.getByLabelText("你的下一行"), "  定义域是 x>0  ");
    await user.click(button);

    expect(onSubmit).toHaveBeenCalledWith("定义域是 x>0");
  });
});