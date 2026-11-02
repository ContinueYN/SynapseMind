import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { IntakeView } from "./IntakeView";
import type { DomainIntake, GenericReview } from "@/src/lib/api/types";

const GENERIC: DomainIntake = {
  version: "0.5",
  domain: {
    name: "generic",
    label: "通用问题",
    verification: "argumentative",
    generic: true,
    confidence: 0,
  },
  one_line: "按「通用问题」处理（论证结构）。没有参考结构，先不判断卡点。",
  checklist: ["目标：这一轮想解决什么", "约束：哪些条件不能动"],
  observed: [],
  gaps: [],
  clarifier: "只问一个：这更像代码问题、决策问题，还是学习/证明题？",
  next_step: "补一句话：卡住的那一步在哪个动作上。",
  disclaimer: "不提供唯一正确答案，也不替代医疗、法律或金融专业建议。",
};

const CODE: DomainIntake = {
  ...GENERIC,
  domain: {
    name: "programming",
    label: "编程",
    verification: "executable",
    generic: false,
    confidence: 1,
  },
  clarifier: null,
  disclaimer: "没有运行你的代码，所以这一轮不声称找到 bug。",
};

const WITH_ATTEMPT: DomainIntake = {
  ...GENERIC,
  observed: ["目标", "选项", "风险"],
  gaps: ["没看到约束：时间、钱、关系、不可逆性。", "没看到可逆实验：1–2 周内能先试哪一步。"],
};

const GENERATED: DomainIntake = {
  ...GENERIC,
  origin: "system",
  graph: [
    { kind: "goal", label: "目标", text: "决定下一份工作在哪里", source: "system" },
    { kind: "constraint", label: "约束", text: "不想长期两地分居", source: "system" },
    { kind: "decision", label: "选项", text: "接受北京的工作", source: "system" },
    { kind: "decision", label: "选项", text: "留在上海陪家人", source: "system" },
    { kind: "risk", label: "风险", text: "换城市后收入可能下降", source: "system" },
  ],
  verifications: [
    {
      kind: "formal",
      status: "unknown",
      detail: "学生没有写出可形式化的答案，本轮未检查。",
    },
  ],
};

const EXTRACTED: DomainIntake = {
  ...WITH_ATTEMPT,
  origin: "student",
  graph: [
    { kind: "goal", label: "目标", text: "决定在哪里工作", source: "student" },
    { kind: "decision", label: "选项", text: "去北京", source: "student" },
  ],
};

const WITH_PROBE: DomainIntake = {
  ...WITH_ATTEMPT,
  clarifier: null,
  probe: {
    kind: "constraint",
    question: "哪些条件不能动？写一句时间、范围或关系上的限制。",
    answered: 1,
    limit: 3,
  },
};

const REVIEW: GenericReview = {
  version: "0.1",
  session_id: "S_DECISION",
  problem_id: "P_GEN_TEST",
  kind: "structure",
  domain: { name: "decision", label: "生活决策", verification: "argumentative" },
  headline: "看到了部分结构，但还有 1 处没有写到；逐条列在下面。",
  findings: [
    {
      id: "f1",
      kind: "missing_constraint",
      label: "缺约束",
      severity: "blocking",
      summary: "没看到约束：时间、钱、关系、不可逆性。",
      evidence_refs: ["ev1"],
    },
  ],
  evidence: [{ id: "ev1", source: "student", ref: "student", excerpt: "我想两年内转做后端。" }],
  not_checked: ["没有判断内容对错。"],
  next_step: "哪些条件不能动？写一句时间、范围或关系上的限制。",
  disclaimer: "这是结构复盘：不判断观点对错，也不给分。",
};

const WITH_REVIEW: DomainIntake = { ...WITH_ATTEMPT, review: REVIEW };

describe("IntakeView", () => {
  it("never shows a confidence percentage when the domain is a guess", () => {
    render(<IntakeView intake={GENERIC} sessionId="S_GENERIC" />);

    expect(screen.getByText("这次先按通用问题处理")).toBeInTheDocument();
    expect(screen.getByText("通用")).toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
    expect(screen.getByText(/只问一个/)).toBeInTheDocument();
  });

  it("names the verification mode and its disclaimer", () => {
    render(<IntakeView intake={CODE} sessionId="S_CODE" />);

    expect(screen.getByText("按「编程」处理")).toBeInTheDocument();
    expect(screen.getByText(/编程 · 可执行验证/)).toBeInTheDocument();
    expect(screen.getByText(/不声称找到 bug/)).toBeInTheDocument();
    expect(screen.queryByText(/只问一个/)).not.toBeInTheDocument();
  });

  it("lists the checklist without claiming a diagnosis", () => {
    render(<IntakeView intake={GENERIC} sessionId="S_GENERIC" />);

    expect(screen.getByText("目标：这一轮想解决什么")).toBeInTheDocument();
    expect(screen.getByText(/不猜卡点、不给唯一答案/)).toBeInTheDocument();
  });

  it("reads the attempt back as seen and missing pieces, never as a verdict", () => {
    render(<IntakeView intake={WITH_ATTEMPT} sessionId="S_DECISION" />);

    expect(screen.getByText(/你写的里面看到了：目标、选项、风险/)).toBeInTheDocument();
    expect(screen.getByText("你写的里面还缺")).toBeInTheDocument();
    expect(
      screen.getByText("没看到约束：时间、钱、关系、不可逆性。"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/错了|不对/)).not.toBeInTheDocument();
  });

  it("shows no seen/missing section when the attempt said nothing", () => {
    render(<IntakeView intake={GENERIC} sessionId="S_GENERIC" />);

    expect(screen.queryByText(/你写的里面看到了/)).not.toBeInTheDocument();
    expect(screen.queryByText("你写的里面还缺")).not.toBeInTheDocument();
  });

  it("shows a generated graph as system structure, not a diagnosis", () => {
    render(<IntakeView intake={GENERATED} sessionId="S_DECISION" />);

    expect(screen.getByText("系统整理的结构")).toBeInTheDocument();
    expect(screen.getByText("决定下一份工作在哪里")).toBeInTheDocument();
    expect(screen.getAllByText("模型整理").length).toBeGreaterThan(0);
    expect(screen.getByText(/不是诊断结论/)).toBeInTheDocument();
    expect(screen.queryByText("从你的话里整理的结构")).not.toBeInTheDocument();
  });

  it("labels an unknown check as not run, never as a pass", () => {
    render(<IntakeView intake={GENERATED} sessionId="S_DECISION" />);

    expect(screen.getByText(/形式检查 · 未检查/)).toBeInTheDocument();
    expect(screen.queryByText(/未发现反例/)).not.toBeInTheDocument();
    expect(screen.queryByText(/通过/)).not.toBeInTheDocument();
  });

  it("asks one missing structure piece and sends the answer back", async () => {
    const onProbe = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <IntakeView
        intake={WITH_PROBE}
        onProbe={onProbe}
        sessionId="S_DECISION"
      />,
    );

    expect(
      screen.getByText(/还缺一块结构：哪些条件不能动/),
    ).toBeInTheDocument();
    expect(screen.getByText(/已补 1\/3 次/)).toBeInTheDocument();

    await user.type(screen.getByLabelText("补这个缺口"), "收入不能降。");
    await user.click(screen.getByRole("button", { name: /补进入口整理/ }));

    expect(onProbe).toHaveBeenCalledWith("收入不能降。");
  });

  it("keeps the student-extracted graph separate from the generated one", () => {
    render(<IntakeView intake={EXTRACTED} sessionId="S_DECISION" />);

    expect(screen.getByText("从你的话里整理的结构")).toBeInTheDocument();
    expect(screen.getByText("决定在哪里工作")).toBeInTheDocument();
    expect(screen.queryByText("模型整理")).not.toBeInTheDocument();
  });

  it("offers the code reproduction form only for an executable intake", () => {
    const { unmount } = render(<IntakeView intake={CODE} sessionId="S_CODE" />);

    expect(screen.getByText(/代码复现卡 · 只跑你显式提交的代码/)).toBeInTheDocument();
    const codeBox = screen.getByLabelText("Python 代码");
    expect(codeBox).toHaveValue("");
    expect(screen.getByText(/不会从题面、作答或轨迹里替你抽代码/)).toBeInTheDocument();

    unmount();
    render(<IntakeView intake={GENERIC} sessionId="S_GENERIC" />);

    expect(screen.queryByText(/代码复现卡/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Python 代码")).not.toBeInTheDocument();
  });

  it("shows the review in place of the old gap list, without stacking both", () => {
    render(<IntakeView intake={WITH_REVIEW} sessionId="S_DECISION" />);

    expect(screen.getByText("结构复盘 · 只看写到没写到")).toBeInTheDocument();
    expect(screen.getByText("缺约束")).toBeInTheDocument();
    // The v0.4 gap list would repeat the same coverage; the review replaces it.
    expect(screen.queryByText("你写的里面还缺")).not.toBeInTheDocument();
    expect(
      screen.queryByText("没看到约束：时间、钱、关系、不可逆性。", {
        selector: "p.sm-note",
      }),
    ).not.toBeInTheDocument();
    // What the student did write is still read back separately.
    expect(screen.getByText(/你写的里面看到了：目标、选项、风险/)).toBeInTheDocument();
  });
});