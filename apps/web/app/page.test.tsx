import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import HomePage from "./page";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  createSession: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/src/lib/api/sessions", () => ({
  createSession: mocks.createSession,
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

function researchSection(): HTMLElement {
  const heading = screen.getByRole("heading", { name: /研究依据/ });
  const section = heading.closest("section");
  if (!section) throw new Error("research section not found");
  return section;
}

beforeEach(() => {
  mocks.push.mockReset();
  mocks.createSession.mockReset();
});

describe("HomePage research basis", () => {
  it("renders every principle with its DOI links", () => {
    render(<HomePage />);
    const section = researchSection();

    expect(
      within(section).getByText("借的是机制，不借效果背书。"),
    ).toBeInTheDocument();
    expect(within(section).getAllByRole("article")).toHaveLength(8);
    expect(within(section).getAllByText("不声称")).toHaveLength(8);

    const links = within(section).getAllByRole("link", { name: /doi:10\./ });
    expect(links).toHaveLength(16);

    for (const link of links) {
      expect(link).toHaveAttribute("href");
      expect(link.getAttribute("href")).toMatch(/^https:\/\/doi\.org\/10\./);
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noreferrer");
    }

    expect(
      links.some(
        (link) =>
          link.getAttribute("href") ===
          "https://doi.org/10.1038/sj.npp.1301559",
      ),
    ).toBe(true);
    expect(
      links.some(
        (link) =>
          link.getAttribute("href") ===
          "https://doi.org/10.1037/h0023816",
      ),
    ).toBe(true);
  });

  it("states the design-source boundary verbatim", () => {
    render(<HomePage />);
    const section = researchSection();

    expect(
      within(section).getByText(
        "这些文献解释设计来源，不证明本产品有效；没有对照实验或提分数据。",
      ),
    ).toBeInTheDocument();
    expect(section.textContent).not.toMatch(/IQ|能力分|排名/);
  });

  it("links the deeper science page", () => {
    render(<HomePage />);

    expect(
      within(researchSection()).getByRole("link", {
        name: /五条机制与逐条引用/,
      }),
    ).toHaveAttribute("href", "/science");
  });
});

describe("HomePage auth gate", () => {
  it("sends a 401 from createSession to /login before any generic error", async () => {
    mocks.createSession.mockRejectedValueOnce(
      Object.assign(new Error("需要先登录。"), { status: 401 }),
    );
    const user = userEvent.setup();
    render(<HomePage />);

    await user.click(screen.getByRole("button", { name: /填入示例题/ }));
    await user.click(screen.getByRole("button", { name: /开始拆题/ }));

    await waitFor(() =>
      expect(mocks.push).toHaveBeenCalledWith("/login?next=/"),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps the ordinary failure path for a non-auth error", async () => {
    mocks.createSession.mockRejectedValueOnce(new Error("服务暂时不可用。"));
    const user = userEvent.setup();
    render(<HomePage />);

    await user.click(screen.getByRole("button", { name: /填入示例题/ }));
    await user.click(screen.getByRole("button", { name: /开始拆题/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "服务暂时不可用。",
    );
    expect(mocks.push).not.toHaveBeenCalled();
  });
});