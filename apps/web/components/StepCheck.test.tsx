import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StepCheck } from "./StepCheck";
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
  return { version: "0.2", status, detail, findings };
}

async function openAndType(text: string) {
  const user = userEvent.setup();
  render(<StepCheck sessionId="S_ABC123456789" />);
  await user.click(screen.getByRole("button", { name: /有一步拿不准/ }));
  await user.type(screen.getByLabelText("这一步"), text);
  return user;
}

describe("StepCheck", () => {
  beforeEach(() => {
    verify.mockReset();
  });

  it("stays collapsed until the student asks for it", async () => {
    const user = userEvent.setup();
    render(<StepCheck sessionId="S_ABC123456789" />);

    expect(screen.queryByLabelText("这一步")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /有一步拿不准/ }));

    expect(screen.getByLabelText("这一步")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /收起/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("sends the trimmed step and shows the structured counterexample", async () => {
    verify.mockResolvedValue(
      verdict(
        "fail",
        "这个等号不成立：「x+1 = 2*x」x=0.1 时左边 1.1、右边 0.2",
        [
          {
            kind: "identity",
            left: "x+1",
            right: "2*x",
            summary: "x=0.1 时左边 1.1、右边 0.2",
            counterexample: "x=0.1 时左边 1.1、右边 0.2",
          },
        ],
      ),
    );
    const user = await openAndType("  x+1=2x  ");

    await user.click(screen.getByRole("button", { name: "检查这一步" }));

    await waitFor(() =>
      expect(verify).toHaveBeenCalledWith("S_ABC123456789", {
        text: "x+1=2x",
        node_id: "",
      }),
    );
    expect(await screen.findByText("这个等号不成立")).toBeInTheDocument();
    expect(screen.getByText("x+1 = 2*x")).toBeInTheDocument();
    expect(screen.getByText(/x=0\.1 时左边 1\.1、右边 0\.2/)).toBeInTheDocument();
    expect(screen.getByText("有反例")).toBeInTheDocument();
    // The formula and the counterexample are separate rows now; the client no
    // longer strips the headline prefix out of the free-text detail.
    expect(screen.queryByText(/这个等号不成立：/)).not.toBeInTheDocument();
  });

  it("keeps previous checks visible and labels the latest one", async () => {
    verify
      .mockResolvedValueOnce(
        verdict(
          "fail",
          "这个等号不成立：「x+1 = 2*x」x=0.1 时左边 1.1、右边 0.2",
          [
            {
              kind: "identity",
              left: "x+1",
              right: "2*x",
              summary: "x=0.1 时左边 1.1、右边 0.2",
              counterexample: "x=0.1 时左边 1.1、右边 0.2",
            },
          ],
        ),
      )
      .mockResolvedValueOnce(
        verdict("unknown", "没有找到可机器证明的等号错误；这不等于这一步正确。"),
      );
    const user = await openAndType("x+1=2x");
    const input = screen.getByLabelText("这一步");
    const submit = screen.getByRole("button", { name: "检查这一步" });

    await user.click(submit);
    expect(await screen.findByText("这个等号不成立")).toBeInTheDocument();

    await user.clear(input);
    await user.type(input, "x+1=1+x");
    await user.click(submit);

    expect(await screen.findByText("这一步没判出来")).toBeInTheDocument();
    expect(screen.getByText(/你查的是/)).toHaveTextContent("x+1=1+x");

    const previous = screen.getByRole("region", { name: "之前的检查" });
    expect(within(previous).getByText("x+1=2x")).toBeInTheDocument();
    expect(within(previous).getByText("有反例")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "清空记录" }));

    expect(screen.queryByText("这一步没判出来")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "之前的检查" }),
    ).not.toBeInTheDocument();
  });

  it("keeps at most three checks in the page history", async () => {
    verify.mockResolvedValue(verdict("unknown", "没有找到可机器证明的等号错误。"));
    const user = await openAndType("a=1");
    const input = screen.getByLabelText("这一步");
    const submit = screen.getByRole("button", { name: "检查这一步" });

    for (const step of ["a=2", "a=3", "a=4"]) {
      await user.clear(input);
      await user.type(input, step);
      await user.click(submit);
      await waitFor(() => expect(submit).toBeEnabled());
    }

    const previous = screen.getByRole("region", { name: "之前的检查" });
    expect(within(previous).getAllByRole("listitem")).toHaveLength(2);
    expect(within(previous).getByText("a=3")).toBeInTheDocument();
    expect(within(previous).queryByText("a=1")).not.toBeInTheDocument();
  });

  it("does not turn an unknown verdict into a correctness claim", async () => {
    verify.mockResolvedValue(
      verdict("unknown", "没有找到可机器证明的等号错误；这不等于这一步正确。"),
    );
    const user = await openAndType("x+1=1+x");

    await user.click(screen.getByRole("button", { name: "检查这一步" }));

    expect(await screen.findByText("这一步没判出来")).toBeInTheDocument();
    expect(
      screen.getByText(
        "没判出来不等于这一步正确；系统只检查它能读懂的等号。",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("未证明")).toBeInTheDocument();
  });

  it("shows a transport error and keeps the form usable", async () => {
    verify.mockRejectedValue(new Error("网络断了"));
    const user = await openAndType("x+1=2x");

    await user.click(screen.getByRole("button", { name: "检查这一步" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("网络断了");
    expect(screen.getByRole("button", { name: "检查这一步" })).toBeEnabled();
  });
});