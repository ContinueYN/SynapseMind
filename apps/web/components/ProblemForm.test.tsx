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
  it("does not ask the student to pick a subject", () => {
    render(<Harness />);

    expect(screen.queryByLabelText("学科")).not.toBeInTheDocument();
    expect(screen.getByText("自动识别")).toBeInTheDocument();
  });

  it("blocks an empty problem before calling the API", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn(async () => {});
    render(<Harness onSubmit={onSubmit} />);

    await user.click(screen.getByRole("button", { name: "开始拆题" }));

    expect(screen.getByRole("alert")).toHaveTextContent("先把题目粘进来。");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits trimmed text and the learning mode without a subject", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn(async () => {});
    render(<Harness onSubmit={onSubmit} />);

    await user.type(screen.getByPlaceholderText(/粘贴题目/), "  一物体从静止下落  ");
    await user.type(screen.getByPlaceholderText(/完全不会就写“不会”/), "  5 m/s  ");
    await user.type(screen.getByPlaceholderText(/写多少都行/), "  先算加速度  ");
    await user.click(screen.getByRole("button", { name: "开始拆题" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit).toHaveBeenCalledWith({
      problem: { text: "一物体从静止下落" },
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