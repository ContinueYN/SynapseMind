import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentTracePanel } from "./AgentTracePanel";
import { getAgentTrace, runAgentTrace } from "@/src/lib/api/client";
import type { AgentTrace } from "@/src/lib/api/types";

vi.mock("@/src/lib/api/client", () => ({
  getAgentTrace: vi.fn(),
  runAgentTrace: vi.fn(),
}));

const TRACE: AgentTrace = {
  version: "0.2",
  session_id: "S_CODE",
  mode: "rules",
  steps: [
    {
      index: 1,
      tool: "check_structure",
      status: "ok",
      input_summary: "domain=programming; verification=executable; intake=generic",
      output_summary: "看到 2 项结构，缺口 1 个；缺口只说明没写到，不判断对错。",
      duration_ms: 1.2,
      citations: [],
    },
    {
      index: 2,
      tool: "search_patterns",
      status: "ok",
      input_summary: "domain=programming; query=concept-label",
      output_summary: "检索到 1 张卡；只作参考，不替代你的判断。",
      duration_ms: 2.4,
      citations: [
        {
          card_id: "K_CODE_TEST_FIRST",
          title: "先写一个最小可复现测试",
          source_title: "Python 文档：unittest",
          source_url: "https://docs.python.org/3/library/unittest.html",
          license: "PSF-2.0",
        },
      ],
    },
    {
      index: 3,
      tool: "ask_clarifying",
      status: "ok",
      input_summary: "kind=action; answered=1/3",
      output_summary: "入口还有一个结构问题；一次只问一个，不推进会话。",
      duration_ms: 0.8,
      citations: [],
    },
  ],
  suggestions: [
    {
      kind: "clarify",
      text: "先回答：最小复现是什么？",
      source: "system",
    },
  ],
  reflection: {
    focus: "目前最明显的结构缺口：先写一个最小复现。",
    next: "先回答：最小复现是什么？",
    boundary: "复盘只引用结构缺口与工具状态；不判断对错，不替你做选择。",
  },
  limits: { max_steps: 3, steps_used: 3 },
  notice:
    "只读工具轨迹：不推进会话、不判断对错、不替你做选择，也没有读取答案。",
};

describe("AgentTracePanel", () => {
  beforeEach(() => {
    vi.mocked(getAgentTrace).mockReset();
    vi.mocked(runAgentTrace).mockReset();
  });

  it("loads a bounded trace and shows its citations", async () => {
    vi.mocked(getAgentTrace).mockResolvedValue(TRACE);
    const user = userEvent.setup();

    render(<AgentTracePanel sessionId="S_CODE" verification="executable" />);

    expect(screen.queryByText("看结构")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /看工具轨迹/ }));

    expect(await screen.findByText("看结构")).toBeInTheDocument();
    expect(screen.getByText("查知识卡")).toBeInTheDocument();
    expect(screen.getByText("提一个澄清问题")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Python 文档：unittest" }),
    ).toHaveAttribute(
      "href",
      "https://docs.python.org/3/library/unittest.html",
    );
    expect(screen.getByText(/上限 3 步，本轮用 3 步/)).toBeInTheDocument();
    expect(screen.getByText(/目前最明显的结构缺口/)).toBeInTheDocument();
    expect(screen.getByText(/复盘只引用结构缺口/)).toBeInTheDocument();
    expect(screen.getByText(/没有读取答案/)).toBeInTheDocument();
    expect(getAgentTrace).toHaveBeenCalledWith("S_CODE");
  });

  it("runs only code the user pasted and sends the optional tests", async () => {
    vi.mocked(runAgentTrace).mockResolvedValue({
      ...TRACE,
      steps: [
        (TRACE.steps ?? [])[0]!,
        {
          index: 2,
          tool: "run_code",
          status: "skipped",
          input_summary: "language=python; code_chars=12; tests_chars=0; explicit=true",
          output_summary: "执行开关关闭：没有运行代码，也不把未运行当作通过。",
          duration_ms: 0.4,
          citations: [],
        },
      ],
    });
    const user = userEvent.setup();

    render(<AgentTracePanel sessionId="S_CODE" verification="executable" />);

    await user.click(screen.getByRole("button", { name: /看工具轨迹/ }));
    await user.type(screen.getByLabelText("Python 代码"), "print(1)\n");
    await user.type(screen.getByLabelText("可选：unittest 测试文件"), "assert True\n");
    await user.click(screen.getByRole("button", { name: /运行并记录轨迹/ }));

    await waitFor(() =>
      expect(runAgentTrace).toHaveBeenCalledWith("S_CODE", {
        code: "print(1)",
        tests: "assert True",
      }),
    );
    expect(await screen.findByText("运行复现")).toBeInTheDocument();
    expect(screen.getByText(/· 未运行/)).toBeInTheDocument();
    expect(screen.getByText(/没有运行代码，也不把未运行当作通过/)).toBeInTheDocument();
  });

  it("does not offer a code box outside an executable framework", async () => {
    vi.mocked(getAgentTrace).mockResolvedValue(TRACE);
    const user = userEvent.setup();

    render(<AgentTracePanel sessionId="S_DECISION" verification="argumentative" />);

    await user.click(screen.getByRole("button", { name: /看工具轨迹/ }));

    expect(await screen.findByText("看结构")).toBeInTheDocument();
    expect(screen.queryByLabelText("Python 代码")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /运行并记录/ })).not.toBeInTheDocument();
  });

  it("shows the API error without hiding the panel", async () => {
    vi.mocked(getAgentTrace).mockRejectedValue(new Error("工具轨迹只用于入口会话。"));
    const user = userEvent.setup();

    render(<AgentTracePanel sessionId="S_GRAPH" verification="formal" />);

    await user.click(screen.getByRole("button", { name: /看工具轨迹/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("工具轨迹只用于入口会话。");
    expect(screen.getByText("看看系统能查到什么，不能查到什么")).toBeInTheDocument();
  });
});