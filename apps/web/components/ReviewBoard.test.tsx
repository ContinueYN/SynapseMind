import type { ReactNode } from "react";

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewBoard } from "./ReviewBoard";
import { REVIEW_DRAFTS_KEY, downloadReviewCsv } from "./review-sheet";
import { listReviewItems } from "@/src/lib/api/client";
import type { ReviewItem } from "@/src/lib/api/types";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/src/lib/api/client", () => ({
  API_BASE: "http://localhost:8000",
  listReviewItems: vi.fn(),
}));

vi.mock("@/components/review-sheet", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/components/review-sheet")>();
  return { ...actual, downloadReviewCsv: vi.fn() };
});

const list = vi.mocked(listReviewItems);
const download = vi.mocked(downloadReviewCsv);

const ITEM: ReviewItem = {
  session_id: "S_ABC123456789",
  problem_id: "P_PUB_002",
  layer: "L2",
  label: "概念不清：恒成立与最值",
  node_id: "n3",
  one_line: "漏掉了 a≤0 这一支。",
  confidence: 0.86,
  created_at: "2026-10-31T08:00:00+00:00",
};

const ITEM2: ReviewItem = {
  ...ITEM,
  session_id: "S_DEF987654321",
  node_id: "n2",
  one_line: "只讨论了 a>0。",
};

function listing(items: ReviewItem[]) {
  return { version: "0.1" as const, items };
}

describe("ReviewBoard", () => {
  beforeEach(() => {
    window.localStorage.clear();
    list.mockReset();
    download.mockReset();
  });

  it("lists each disagreed card with its layer, time and confidence", async () => {
    list.mockResolvedValue(listing([ITEM, ITEM2]));
    render(<ReviewBoard />);

    expect(await screen.findAllByText(ITEM.label)).toHaveLength(2);
    const queue = screen.getByRole("region", { name: "异议队列" });
    expect(within(queue).getAllByRole("listitem")).toHaveLength(2);
    expect(within(queue).getAllByText("2026-10-31 08:00 UTC")).toHaveLength(2);
    expect(within(queue).getAllByText("把握 86%")).toHaveLength(2);
    expect(within(queue).getAllByText("L2")).toHaveLength(2);
    expect(screen.getByLabelText("队列概况")).toHaveTextContent("2条异议");
    expect(screen.getByLabelText("队列概况")).toHaveTextContent("0已判断");
  });

  it("marks a judgment, counts it, and keeps it in local storage", async () => {
    list.mockResolvedValue(listing([ITEM]));
    const user = userEvent.setup();
    render(<ReviewBoard />);

    await screen.findByText(ITEM.label);
    await user.click(screen.getByRole("button", { name: "说得通但不对" }));

    expect(
      screen.getByRole("button", { name: "说得通但不对" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("队列概况")).toHaveTextContent("1已判断");
    expect(
      JSON.parse(window.localStorage.getItem(REVIEW_DRAFTS_KEY) ?? "{}"),
    ).toEqual({
      [ITEM.session_id]: { judgment: "plausible_wrong", note: "" },
    });

    // Clicking the same choice again takes the judgment back.
    await user.click(screen.getByRole("button", { name: "说得通但不对" }));

    expect(
      screen.getByRole("button", { name: "说得通但不对" }),
    ).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByLabelText("队列概况")).toHaveTextContent("0已判断");
  });

  it("restores saved judgments and notes after a reload", async () => {
    window.localStorage.setItem(
      REVIEW_DRAFTS_KEY,
      JSON.stringify({
        [ITEM.session_id]: { judgment: "vague", note: "太泛，没指到那一步" },
      }),
    );
    list.mockResolvedValue(listing([ITEM]));
    render(<ReviewBoard />);

    await screen.findByText(ITEM.label);
    expect(screen.getByRole("button", { name: "空泛" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByLabelText(`${ITEM.session_id} 的备注`)).toHaveValue(
      "太泛，没指到那一步",
    );
    expect(screen.getByLabelText("队列概况")).toHaveTextContent("1已判断");
  });

  it("exports the queue and the judgment as CSV", async () => {
    list.mockResolvedValue(listing([ITEM]));
    const user = userEvent.setup();
    render(<ReviewBoard />);

    await screen.findByText(ITEM.label);
    await user.click(screen.getByRole("button", { name: "准确" }));
    await user.click(screen.getByRole("button", { name: "导出 CSV" }));

    expect(download).toHaveBeenCalledTimes(1);
    const [csv, filename] = download.mock.calls[0];
    expect(filename).toMatch(/^review-\d{8}-\d{4}\.csv$/);
    expect(csv).toContain(ITEM.session_id);
    expect(csv).toContain("准确");
    expect(csv).toContain("0.86");
    expect(await screen.findByRole("status")).toHaveTextContent(
      "已导出 1 条，其中 1 条带人工判断。",
    );
  });

  it("clears local judgments without touching the queue", async () => {
    list.mockResolvedValue(listing([ITEM]));
    const user = userEvent.setup();
    render(<ReviewBoard />);

    await screen.findByText(ITEM.label);
    await user.click(screen.getByRole("button", { name: "空泛" }));
    await user.click(screen.getByRole("button", { name: "清空判断" }));

    expect(window.localStorage.getItem(REVIEW_DRAFTS_KEY)).toBe("{}");
    expect(screen.getByRole("button", { name: "空泛" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(
      screen.queryByRole("button", { name: "清空判断" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(ITEM.label)).toBeInTheDocument();
  });

  it("shows an empty state and disables export", async () => {
    list.mockResolvedValue(listing([]));
    render(<ReviewBoard />);

    expect(await screen.findByText("还没有异议记录。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "导出 CSV" })).toBeDisabled();
  });

  it("recovers from a failed load when the reviewer retries", async () => {
    list
      .mockRejectedValueOnce(new Error("连不上诊断服务"))
      .mockResolvedValueOnce(listing([ITEM]));
    const user = userEvent.setup();
    render(<ReviewBoard />);

    expect(await screen.findByText("复核队列没打开")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "连不上诊断服务",
    );
    expect(screen.getByText(/http:\/\/localhost:8000/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "重试" }));

    expect(await screen.findByText(ITEM.label)).toBeInTheDocument();
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
  });
});