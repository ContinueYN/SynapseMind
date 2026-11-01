import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { IntakeView } from "./IntakeView";
import type { DomainIntake } from "@/src/lib/api/types";

const GENERIC: DomainIntake = {
  version: "0.1",
  domain: {
    name: "generic",
    label: "通用问题",
    verification: "argumentative",
    generic: true,
    confidence: 0,
  },
  one_line: "按「通用问题」处理（论证结构）。没有参考结构，先不判断卡点。",
  checklist: ["目标：这一轮想解决什么", "约束：哪些条件不能动"],
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
});