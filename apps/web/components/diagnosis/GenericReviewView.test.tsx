import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GenericReviewView } from "./GenericReviewView";
import { runReview } from "@/src/lib/api/review";
import type { GenericReview } from "@/src/lib/api/types";

vi.mock("@/src/lib/api/review", () => ({
  runReview: vi.fn(),
}));

function expectNoRankingDom(container: HTMLElement) {
  expect(container.textContent ?? "").not.toMatch(/\b(score|rank|recommended)\b/i);
  expect(
    container.querySelector(
      "[data-score], [data-rank], [data-recommended], .score, .rank, .recommended",
    ),
  ).toBeNull();
  expect(screen.queryByRole("radio")).toBeNull();
}

const STRUCTURE: GenericReview = {
  version: "0.1",
  session_id: "S_REVIEW",
  problem_id: "P_GEN_REVIEW",
  kind: "structure",
  domain: { name: "writing", label: "写作", verification: "argumentative" },
  headline: "看到了部分结构，但还有 1 处没有写到；逐条列在下面。",
  findings: [
    {
      id: "f1",
      kind: "missing_evidence",
      label: "缺证据",
      severity: "blocking",
      summary: "没看到支撑结论的事实或引文。",
      evidence_refs: ["ev1", "ev2"],
    },
  ],
  evidence: [
    { id: "ev1", source: "student", ref: "student", excerpt: "我想论证远程办公更好。" },
    { id: "ev2", source: "graph", ref: "n1", excerpt: "远程办公更好" },
  ],
  not_checked: ["没有判断内容对错；只检查这次提交里有没有写到这些结构。"],
  next_step: "有哪些事实、数据或引文在支撑它？",
  disclaimer: "这是结构复盘：只说明写到或没写到哪些结构，不判断观点对错，也不给分。",
};

const STRUCTURE_WITH_KNOWLEDGE: GenericReview = {
  ...STRUCTURE,
  evidence: [
    ...(STRUCTURE.evidence ?? []),
    {
      id: "ev3",
      source: "knowledge",
      ref: "K_WRITING_CLAIM_EVIDENCE",
      excerpt: "主张、理由、证据分开写",
    },
  ],
};

const DECISION: GenericReview = {
  version: "0.1",
  session_id: "S_REVIEW",
  problem_id: "P_GEN_REVIEW",
  kind: "decision",
  domain: { name: "decision", label: "生活决策", verification: "argumentative" },
  headline: "整理出 3 个选项（含「什么都不做」）：1 个写了代价，1 个写了风险，0 个写了可逆实验。",
  findings: [
    {
      id: "f1",
      kind: "missing_goal",
      label: "缺目标",
      severity: "blocking",
      summary: "没看到目标：这一轮最想解决或得到什么，还没有写。",
      evidence_refs: ["ev1"],
    },
  ],
  evidence: [{ id: "ev1", source: "student", ref: "student", excerpt: "要么留下，要么跳槽。" }],
  not_checked: ["没有判断哪个选项更好，也没有排序或推荐。"],
  next_step: "先挑一个选项，写一个 1–2 周内能撤回的小实验，好吗？",
  disclaimer: "这是决策框：只列选项、代价、风险与可逆实验，不排序、不推荐，也不替你做选择。",
  options: [
    { label: "留在公司转岗", costs: ["涨薪慢"], risks: [], reversible_test: "" },
    { label: "跳槽去小厂", costs: [], risks: ["收入可能下降"], reversible_test: "先面两家试试" },
    { label: "什么都不做（先不决定）", costs: [], risks: [], reversible_test: "" },
  ],
  tradeoff_question: "如果更看重「留在公司转岗」，你愿意接受「跳槽去小厂」的代价吗？",
};

const EXECUTION_SKIPPED: GenericReview = {
  version: "0.1",
  session_id: "S_CODE",
  problem_id: "P_CODE",
  kind: "execution",
  domain: { name: "programming", label: "编程", verification: "executable" },
  headline: "没有运行：本地执行开关关闭（SYNAPSE_EXEC=off）。",
  findings: [],
  evidence: [],
  not_checked: ["没有判断代码是否正确，也没有运行你提交以外的隐藏测试。"],
  next_step: "需要复现时，先设置 SYNAPSE_EXEC=on 再重新提交这段代码；也可以先看工具轨迹里的结构线索。",
  disclaimer: "这是代码复现卡，不是诊断结论。skipped 只表示这次没有运行，不表示代码正确或通过。",
  execution: { status: "skipped", tests_submitted: false },
};

const EXECUTION_FAIL: GenericReview = {
  ...EXECUTION_SKIPPED,
  headline: "这次运行没有通过：AssertionError: Lists differ: [2, 1, 3] != [1, 2, 3]",
  findings: [
    {
      id: "f1",
      kind: "test_failure",
      label: "首个失败",
      severity: "blocking",
      summary: "AssertionError: Lists differ: [2, 1, 3] != [1, 2, 3]",
      evidence_refs: ["ev1"],
    },
  ],
  evidence: [
    {
      id: "ev1",
      source: "execution",
      ref: "run",
      excerpt: "运行状态=fail；退出码=1；耗时=12ms",
    },
  ],
  execution: {
    status: "fail",
    first_failure: "AssertionError: Lists differ: [2, 1, 3] != [1, 2, 3]",
    stdout_excerpt: "FAILED (failures=1)",
    tests_submitted: true,
  },
  disclaimer:
    "这是代码复现卡，不是诊断结论。这次运行没有通过；它只记录本次的退出码与首个失败，不表示已经找到根因。",
};

const EXECUTION_PASS: GenericReview = {
  ...EXECUTION_SKIPPED,
  headline: "这次运行通过：提交的测试通过；这只说明这一次。",
  evidence: [
    {
      id: "ev1",
      source: "execution",
      ref: "run",
      excerpt: "运行状态=pass；退出码=0；耗时=9ms",
    },
  ],
  next_step: "补一个会失败的用例，或把输入缩到最小，确认这次运行真的覆盖了你要验证的行为。",
  disclaimer:
    "这是代码复现卡，不是诊断结论。pass 只表示退出码 0 或提交的测试通过，不表示代码正确或完整。",
  execution: { status: "pass", stdout_excerpt: "ok", tests_submitted: true },
};

const EXECUTION_TIMEOUT: GenericReview = {
  ...EXECUTION_SKIPPED,
  headline: "这次运行超时：进程没有在时限内结束。",
  findings: [
    {
      id: "f1",
      kind: "execution_timeout",
      label: "运行超时",
      severity: "blocking",
      summary: "超过 5 秒墙钟上限，进程已被终止；没有结果。",
      evidence_refs: ["ev1"],
    },
  ],
  evidence: [
    {
      id: "ev1",
      source: "execution",
      ref: "run",
      excerpt: "运行状态=timeout；退出码=无；耗时=5000ms",
    },
  ],
  execution: { status: "timeout", stdout_excerpt: "start", tests_submitted: false },
};

const EXECUTION_REJECTED: GenericReview = {
  ...EXECUTION_SKIPPED,
  headline: "执行被拒绝：代码没有运行。",
  findings: [
    {
      id: "f1",
      kind: "execution_rejected",
      label: "执行被拒绝",
      severity: "blocking",
      summary: "提交没有运行：静态检查拒绝了代码。",
      evidence_refs: ["ev1"],
    },
  ],
  evidence: [
    {
      id: "ev1",
      source: "execution",
      ref: "run",
      excerpt: "运行状态=rejected；代码没有运行；提交没有运行：静态检查拒绝了代码。",
    },
  ],
  execution: { status: "rejected", tests_submitted: false },
};

describe("GenericReviewView", () => {
  beforeEach(() => {
    vi.mocked(runReview).mockReset();
  });

  it("renders a structure review as coverage, not a verdict", () => {
    const { container } = render(<GenericReviewView review={STRUCTURE} />);

    expect(screen.getByText("结构复盘 · 只看写到没写到")).toBeInTheDocument();
    expect(screen.getByText(STRUCTURE.headline)).toBeInTheDocument();
    expect(screen.getByText("缺证据")).toBeInTheDocument();
    expect(screen.getByText("没看到支撑结论的事实或引文。")).toBeInTheDocument();
    expect(screen.getByText("主要缺口")).toBeInTheDocument();
    expect(screen.getByText(/证据 2 条：学生原话 1 条、结构图 1 条/)).toBeInTheDocument();
    expect(screen.getByText("这次没有检查")).toBeInTheDocument();
    expect(screen.getByText(STRUCTURE.not_checked![0])).toBeInTheDocument();
    expect(screen.getByText(STRUCTURE.next_step)).toBeInTheDocument();
    expect(screen.getByText(STRUCTURE.disclaimer)).toBeInTheDocument();
    expect(screen.queryByText("决策框 · 不排序、不推荐")).not.toBeInTheDocument();
    expectNoRankingDom(container);
  });

  it("lists retrieved knowledge cards by id and title without a score", () => {
    const { container } = render(<GenericReviewView review={STRUCTURE_WITH_KNOWLEDGE} />);

    expect(screen.getByText("可追来源")).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "知识卡来源（id 与标题）" });
    expect(within(list).getByText("K_WRITING_CLAIM_EVIDENCE")).toBeInTheDocument();
    expect(within(list).getByText("主张、理由、证据分开写")).toBeInTheDocument();
    // The knowledge card is counted as evidence but not turned into a finding.
    expect(
      screen.getByText(/证据 3 条：学生原话 1 条、结构图 1 条、知识卡 1 条/),
    ).toBeInTheDocument();
    expect(screen.getByText(/不显示相似度分数/)).toBeInTheDocument();
    expectNoRankingDom(container);
  });

  it("lists decision options in the order they were written", () => {
    const { container } = render(<GenericReviewView review={DECISION} />);

    expect(screen.getByText("决策框 · 不排序、不推荐")).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "选项（按你写到的顺序）" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent("留在公司转岗");
    expect(items[1]).toHaveTextContent("跳槽去小厂");
    expect(items[2]).toHaveTextContent("什么都不做（先不决定）");
    // Order is the submitted one, not a ranking: the last option is still last.
    expect(items[0]).not.toHaveTextContent("跳槽去小厂");
    expectNoRankingDom(container);
  });

  it("shows costs, risks and reversible tests without decorating an option", () => {
    render(<GenericReviewView review={DECISION} />);

    const items = within(
      screen.getByRole("list", { name: "选项（按你写到的顺序）" }),
    ).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent(/留在公司转岗/);
    expect(items[0]).toHaveTextContent(/代价：涨薪慢/);
    expect(items[1]).toHaveTextContent(/风险：收入可能下降/);
    expect(items[1]).toHaveTextContent(/可逆实验：先面两家试试/);
    // Empty fields are reported as missing, never filled with advice.
    expect(screen.getAllByText(/还没写/).length).toBeGreaterThan(0);
    expect(screen.getByText(/取舍问题：/)).toBeInTheDocument();
    expect(screen.queryByText(/推荐选项|最佳选项|建议选/)).not.toBeInTheDocument();
  });

  it("offers the code box only for an executable session", () => {
    const { container, rerender } = render(
      <GenericReviewView review={null} verification="argumentative" sessionId="S_DECISION" />,
    );
    expect(container).toBeEmptyDOMElement();

    // A structure review never gets a code box, even with any session id.
    rerender(
      <GenericReviewView
        review={STRUCTURE}
        verification="executable"
        sessionId="S_CODE"
      />,
    );
    expect(screen.queryByLabelText("Python 代码")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /运行并生成复现卡/ })).not.toBeInTheDocument();
  });

  it("does not run anything until the user explicitly submits", async () => {
    vi.mocked(runReview).mockResolvedValue(EXECUTION_PASS);
    const user = userEvent.setup();

    render(
      <GenericReviewView review={null} verification="executable" sessionId="S_CODE" />,
    );

    const codeBox = screen.getByLabelText("Python 代码");
    const testsBox = screen.getByLabelText("可选：unittest 测试文件");
    // The boxes start empty; nothing is prefilled from the problem or attempt.
    expect(codeBox).toHaveValue("");
    expect(testsBox).toHaveValue("");
    expect(runReview).not.toHaveBeenCalled();

    const submit = screen.getByRole("button", { name: /运行并生成复现卡/ });
    expect(submit).toBeDisabled();
    expect(screen.getByText(/还没有运行/)).toBeInTheDocument();

    await user.type(codeBox, "print('ok')\n");
    await user.type(testsBox, "assert True\n");
    await user.click(submit);

    await waitFor(() =>
      expect(runReview).toHaveBeenCalledWith("S_CODE", {
        code: "print('ok')",
        tests: "assert True",
      }),
    );
    expect(await screen.findByText("这次运行通过（pass）")).toBeInTheDocument();
    expect(
      screen.getAllByText(/pass 只表示退出码 0 或提交的测试通过/).length,
    ).toBeGreaterThan(0);
  });

  it("renders skipped as not run, never as a pass", () => {
    render(
      <GenericReviewView
        review={EXECUTION_SKIPPED}
        verification="executable"
        sessionId="S_CODE"
      />,
    );

    expect(
      screen.getByText("没有运行（skipped），执行开关关闭"),
    ).toBeInTheDocument();
    expect(screen.queryByText("这次运行通过（pass）")).not.toBeInTheDocument();
    expect(
      screen.getAllByText(/skipped 只表示这次没有运行/).length,
    ).toBeGreaterThan(0);
    // The form stays available so the student can enable the switch and resubmit.
    expect(screen.getByLabelText("Python 代码")).toHaveValue("");
  });

  it("shows the first failure of a failed run", () => {
    render(
      <GenericReviewView
        review={EXECUTION_FAIL}
        verification="executable"
        sessionId="S_CODE"
      />,
    );

    expect(screen.getByText("这次运行没有通过（fail）")).toBeInTheDocument();
    expect(screen.getAllByText("首个失败").length).toBeGreaterThan(0);
    expect(
      screen.getAllByText(/AssertionError: Lists differ/).length,
    ).toBeGreaterThan(0);
    expect(screen.getByText("FAILED (failures=1)")).toBeInTheDocument();
    expect(screen.getAllByText(/不表示已经找到根因/).length).toBeGreaterThan(0);
  });

  it("keeps timeout and rejected distinct from pass and fail", () => {
    const { rerender } = render(
      <GenericReviewView
        review={EXECUTION_TIMEOUT}
        verification="executable"
        sessionId="S_CODE"
      />,
    );
    expect(screen.getByText("运行超时（timeout）")).toBeInTheDocument();
    expect(screen.getByText(/timeout 只表示进程没有在时限内结束/)).toBeInTheDocument();
    expect(screen.queryByText(/这次运行通过/)).not.toBeInTheDocument();

    rerender(
      <GenericReviewView
        review={EXECUTION_REJECTED}
        verification="executable"
        sessionId="S_CODE"
      />,
    );
    expect(
      screen.getByText("执行被拒绝（rejected），代码没有运行"),
    ).toBeInTheDocument();
    expect(screen.getByText(/rejected 表示静态闸门拒绝了代码/)).toBeInTheDocument();
    expect(screen.queryByText("输出摘要")).not.toBeInTheDocument();
    expect(screen.queryByText("首个失败")).not.toBeInTheDocument();
  });

  it("shows an API error without losing the card", async () => {
    vi.mocked(runReview).mockRejectedValue(new Error("代码复现卡只用于可执行验证的会话。"));
    const user = userEvent.setup();

    render(
      <GenericReviewView review={null} verification="executable" sessionId="S_CODE" />,
    );

    await user.type(screen.getByLabelText("Python 代码"), "print(1)");
    await user.click(screen.getByRole("button", { name: /运行并生成复现卡/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "代码复现卡只用于可执行验证的会话。",
    );
    expect(screen.getByLabelText("Python 代码")).toHaveValue("print(1)");
  });
});