import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CardPage from "./page";
import { getSession } from "@/src/lib/api/sessions";

vi.mock("next/navigation", () => ({
  useParams: () => ({ sessionId: "S_CARD" }),
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/src/lib/api/sessions", () => ({
  exitSession: vi.fn(),
  getSession: vi.fn(),
}));

vi.mock("@/src/lib/api/http", () => ({
  isUnauthorized: (error: unknown) =>
    Boolean(
      error &&
        typeof error === "object" &&
        "status" in error &&
        (error as { status?: number }).status === 401,
    ),
}));

describe("CardPage auth gate", () => {
  beforeEach(() => {
    vi.mocked(getSession).mockReset();
  });

  it("shows a sign-in card on 401 and keeps the card path as next", async () => {
    vi.mocked(getSession).mockRejectedValueOnce(
      new (class extends Error {
        readonly status = 401;
      })("需要先登录。"),
    );

    render(<CardPage />);

    expect(await screen.findByText("请先登录")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /去登录/ }),
    ).toHaveAttribute("href", "/login?next=%2Fcard%2FS_CARD");
    expect(screen.queryByText("卡点卡没打开")).not.toBeInTheDocument();
  });

  it("keeps the ordinary failure path when auth is not the cause", async () => {
    vi.mocked(getSession).mockRejectedValueOnce(
      new Error("加载卡点卡失败。"),
    );

    render(<CardPage />);

    expect(await screen.findByText("卡点卡没打开")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "加载卡点卡失败。" })).toBeInTheDocument();
    expect(screen.queryByText("请先登录")).not.toBeInTheDocument();
  });
});