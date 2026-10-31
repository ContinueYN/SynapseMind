import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PhysicsStepCheck } from "./PhysicsStepCheck";
import { verifyStep } from "@/src/lib/api/client";
import type { StepVerdict } from "@/src/lib/api/types";

vi.mock("@/src/lib/api/client", () => ({
  verifyStep: vi.fn(),
}));

const verify = vi.mocked(verifyStep);

function verdict(
  status: StepVerdict["status"],
  detail: string,
  findings: NonNullable<StepVerdict["findings"]> = [],
): StepVerdict {
  return { version: "0.3", status, detail, findings };
}

async function open() {
  const user = userEvent.setup();
  render(<PhysicsStepCheck sessionId="S_PHY123456789" />);
  await user.click(screen.getByRole("button", { name: /有一步拿不准/ }));
  return user;
}

describe("PhysicsStepCheck", () => {
  beforeEach(() => {
    verify.mockReset();
  });

  it("sends equation, units and values as a structured payload", async () => {
    verify.mockResolvedValue(verdict("pass", "量纲一致，数值回代未发现矛盾。"));
    const user = await open();

    await user.type(screen.getByLabelText("这一步"), "F - mu*N = m*a");
    fireEvent.change(screen.getByLabelText("符号单位"), {
      target: { value: "F=N\nm=kg\na=m/s^2\nmu=" },
    });
    fireEvent.change(screen.getByLabelText("数值"), {
      target: { value: "F=10\nm=2\na=3\nmu=0.2" },
    });

    await user.click(screen.getByRole("button", { name: "检查这一步" }));

    await waitFor(() =>
      expect(verify).toHaveBeenCalledWith("S_PHY123456789", {
        text: "F - mu*N = m*a",
        node_id: "",
        data: {
          equation: "F - mu*N = m*a",
          units: { F: "N", m: "kg", a: "m/s^2", mu: "" },
          values: { F: 10, m: 2, a: 3, mu: 0.2 },
        },
      }),
    );
    expect(await screen.findByText("没发现不一致")).toBeInTheDocument();
    expect(screen.getByText("已检查")).toBeInTheDocument();
    expect(
      screen.getByText("只说明跑过的量纲/回代检查没有矛盾，不是整步证明。"),
    ).toBeInTheDocument();
  });

  it("sends a declared result and relative tolerance with the numeric replay", async () => {
    verify.mockResolvedValue(verdict("pass", "声明结果值与单位一致。"));
    const user = await open();

    await user.type(screen.getByLabelText("这一步"), "m*a");
    await user.type(screen.getByLabelText("结果单位"), "N");
    fireEvent.change(screen.getByLabelText("符号单位"), {
      target: { value: "m=kg\na=m/s^2" },
    });
    fireEvent.change(screen.getByLabelText("数值"), {
      target: { value: "m=2\na=3" },
    });
    await user.type(screen.getByLabelText("你写的结果"), "6");
    await user.type(screen.getByLabelText("相对容差"), "1");

    await user.click(screen.getByRole("button", { name: "检查这一步" }));

    await waitFor(() =>
      expect(verify).toHaveBeenCalledWith("S_PHY123456789", {
        text: "m*a",
        node_id: "",
        data: {
          expression: "m*a",
          unit: "N",
          units: { m: "kg", a: "m/s^2" },
          values: { m: 2, a: 3 },
          expected: { value: 6, unit: "N" },
          tolerance: { relative: 0.01 },
        },
      }),
    );
  });

  it("sends a ± result as a structured uncertainty", async () => {
    verify.mockResolvedValue(verdict("pass", "声明结果落在不确定度内。"));
    const user = await open();

    await user.type(screen.getByLabelText("这一步"), "m*a");
    await user.type(screen.getByLabelText("结果单位"), "N");
    fireEvent.change(screen.getByLabelText("符号单位"), {
      target: { value: "m=kg\na=m/s^2" },
    });
    fireEvent.change(screen.getByLabelText("数值"), {
      target: { value: "m=2\na=3" },
    });
    await user.type(screen.getByLabelText("你写的结果"), "6±0.1");

    await user.click(screen.getByRole("button", { name: "检查这一步" }));

    await waitFor(() =>
      expect(verify).toHaveBeenCalledWith("S_PHY123456789", {
        text: "m*a",
        node_id: "",
        data: {
          expression: "m*a",
          unit: "N",
          units: { m: "kg", a: "m/s^2" },
          values: { m: 2, a: 3 },
          expected: { value: 6, uncertainty: 0.1, unit: "N" },
        },
      }),
    );
  });

  it("sends an absolute tolerance in the result unit", async () => {
    verify.mockResolvedValue(verdict("pass", "声明结果值与单位一致。"));
    const user = await open();

    await user.type(screen.getByLabelText("这一步"), "m*a");
    await user.type(screen.getByLabelText("结果单位"), "N");
    fireEvent.change(screen.getByLabelText("符号单位"), {
      target: { value: "m=kg\na=m/s^2" },
    });
    fireEvent.change(screen.getByLabelText("数值"), {
      target: { value: "m=2\na=3" },
    });
    await user.type(screen.getByLabelText("你写的结果"), "6");
    await user.type(screen.getByLabelText("绝对容差"), "0.05");

    await user.click(screen.getByRole("button", { name: "检查这一步" }));

    await waitFor(() =>
      expect(verify).toHaveBeenCalledWith("S_PHY123456789", {
        text: "m*a",
        node_id: "",
        data: {
          expression: "m*a",
          unit: "N",
          units: { m: "kg", a: "m/s^2" },
          values: { m: 2, a: 3 },
          expected: { value: 6, unit: "N" },
          tolerance: { absolute: 0.05 },
        },
      }),
    );
  });

  it("rejects a tolerance without a declared result before calling the API", async () => {
    const user = await open();

    await user.type(screen.getByLabelText("这一步"), "m*a");
    await user.type(screen.getByLabelText("结果单位"), "N");
    await user.type(screen.getByLabelText("绝对容差"), "0.05");
    await user.click(screen.getByRole("button", { name: "检查这一步" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("你写的结果");
    expect(verify).not.toHaveBeenCalled();
  });

  it("stops a local shape error before calling the API", async () => {
    const user = await open();

    await user.type(screen.getByLabelText("这一步"), "m*a");
    await user.click(screen.getByRole("button", { name: "检查这一步" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("结果单位");
    expect(verify).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "检查这一步" })).toBeEnabled();
  });

  it("renders a physics failure as a comparison, not an equality", async () => {
    verify.mockResolvedValue(
      verdict("fail", "数值回代不一致：左侧 3 N、右侧 4 N", [
        {
          kind: "quantity",
          left: "左侧 3 N",
          right: "右侧 4 N",
          summary: "数值回代不一致：左侧 3 N、右侧 4 N",
          counterexample: "",
        },
      ]),
    );
    const user = await open();

    await user.type(screen.getByLabelText("这一步"), "m*a");
    await user.type(screen.getByLabelText("结果单位"), "N");
    await user.click(screen.getByRole("button", { name: "检查这一步" }));

    expect(await screen.findByText("这一步有矛盾")).toBeInTheDocument();
    expect(screen.getByText("左侧 3 N 对照 右侧 4 N")).toBeInTheDocument();
    expect(screen.queryByText("左侧 3 N = 右侧 4 N")).not.toBeInTheDocument();
    expect(screen.getByText("数值回代不一致：左侧 3 N、右侧 4 N")).toBeInTheDocument();
  });

  it("keeps at most three physics checks in the page history", async () => {
    verify.mockResolvedValue(verdict("pass", "量纲一致，数值回代未发现矛盾。"));
    const user = await open();

    await user.type(screen.getByLabelText("这一步"), "m*a");
    await user.type(screen.getByLabelText("结果单位"), "N");
    const input = screen.getByLabelText("这一步");
    const submit = screen.getByRole("button", { name: "检查这一步" });

    for (const expression of ["m*a", "m*a*2", "m*a*3", "m*a*4"]) {
      await user.clear(input);
      await user.type(input, expression);
      await user.click(submit);
      await waitFor(() => expect(submit).toBeEnabled());
    }

    const previous = screen.getByRole("region", { name: "之前的检查" });
    expect(within(previous).getAllByRole("listitem")).toHaveLength(2);
    expect(within(previous).getByText("m*a*3（N）")).toBeInTheDocument();
    expect(within(previous).queryByText("m*a（N）")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "清空记录" }));
    expect(
      screen.queryByRole("region", { name: "之前的检查" }),
    ).not.toBeInTheDocument();
  });

  it("keeps an unknown verdict away from a correctness claim", async () => {
    verify.mockResolvedValue(
      verdict("unknown", "缺少符号 m 的单位，无法做量纲检查。"),
    );
    const user = await open();

    await user.type(screen.getByLabelText("这一步"), "F = m*a");
    await user.click(screen.getByRole("button", { name: "检查这一步" }));

    expect(await screen.findByText("这一步没判出来")).toBeInTheDocument();
    expect(screen.getByText("未证明")).toBeInTheDocument();
    expect(
      screen.getByText("缺单位、缺数值或读不懂，都不等于这一步正确；系统不猜单位。"),
    ).toBeInTheDocument();
  });
});