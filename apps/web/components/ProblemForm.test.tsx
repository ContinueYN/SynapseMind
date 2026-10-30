import { useState } from "react";

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { EMPTY_DRAFT, ProblemForm, type Draft } from "./ProblemForm";
import type { CreateSessionInput } from "@/src/lib/api/types";

function Harness({
  initial = EMPTY_DRAFT,
  onSubmit = vi.fn(async () => {}),
}: {
  initial?: Draft;
  onSubmit?: (input: CreateSessionInput) => Promise<void>;
}) {
  const [draft, setDraft] = useState<Draft>(initial);
  return (
    <ProblemForm
      busy={false}
      error={null}
      onChange={setDraft}
      onSubmit={onSubmit}
      value={draft}
    />
  );
}

describe("ProblemForm", () => {
  it("switches the declared subject", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    const chinese = screen.getByRole("radio", { name: "语文" });
    await user.click(chinese);

    expect(chinese).toBeChecked();
    expect(screen.getByRole("radio", { name: "数学" })).not.toBeChecked();
  });

  it("blocks an empty problem before calling the API", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn(async () => {});
    render(<Harness onSubmit={onSubmit} />);

    await user.click(screen.getByRole("button", { name: "开始拆题" }));

    expect(screen.getByRole("alert")).toHaveTextContent("先把题目粘进来。");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits trimmed text, the chosen subject, and the learning mode", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn(async () => {});
    render(<Harness onSubmit={onSubmit} />);

    await user.click(screen.getByRole("radio", { name: "物理" }));
    await user.type(screen.getByPlaceholderText(/粘贴题目/), "  一物体从静止下落  ");
    await user.type(screen.getByPlaceholderText(/完全不会就写“不会”/), "  5 m/s  ");
    await user.type(screen.getByPlaceholderText(/写多少都行/), "  先算加速度  ");
    await user.click(screen.getByRole("button", { name: "开始拆题" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit).toHaveBeenCalledWith({
      problem: { text: "一物体从静止下落", subject: "physics" },
      attempt: {
        answer: "5 m/s",
        work: "先算加速度",
        stuck_at: undefined,
        self_report: "unsure",
      },
      mode: "learning",
    });
  });

  it("fills the sample and opens the optional section", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "没有题目？填入示例题" }));

    expect(screen.getByDisplayValue(/已知函数 f\(x\)=ln x - a x/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /收起/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByRole("radio", { name: "数学" })).toBeChecked();
  });

  it("disables submission while a session is being created", () => {
    render(
      <ProblemForm
        busy
        error="上次请求失败了吗？"
        onChange={() => {}}
        onSubmit={async () => {}}
        value={EMPTY_DRAFT}
      />,
    );

    expect(screen.getByRole("button", { name: "正在拆题" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("正在读你的过程");
    expect(screen.getByRole("alert")).toHaveTextContent("上次请求失败了吗？");
  });
});