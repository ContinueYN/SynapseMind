import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AccountMenu } from "./AccountMenu";
import type { AuthUser } from "@/src/lib/api/types";

const mocks = vi.hoisted(() => ({
  pathname: "/diagnose/S_1",
  replace: vi.fn(),
  refresh: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname,
  useRouter: () => ({ replace: mocks.replace, refresh: mocks.refresh }),
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

const OWNER: AuthUser = {
  id: "U_OWNER",
  email: "owner@example.com",
  display_name: "小林",
  created_at: "2026-11-02T08:00:00+00:00",
};

function reply(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => (body === undefined ? "" : JSON.stringify(body)),
  } as Response;
}

function fetchReturning(...responses: Response[]) {
  const fetchMock = vi.fn();
  for (const response of responses) fetchMock.mockResolvedValueOnce(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("AccountMenu", () => {
  beforeEach(() => {
    mocks.pathname = "/diagnose/S_1";
    mocks.replace.mockReset();
    mocks.refresh.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders nothing when auth is disabled (403)", async () => {
    const fetchMock = fetchReturning(reply({ detail: "认证未启用。" }, 403));
    const { container } = render(<AccountMenu />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("link", { name: /登录/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /退出/ })).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when /auth/me is unavailable (never a fake prompt)", async () => {
    const fetchMock = fetchReturning(reply({ detail: "not found" }, 404));
    const { container } = render(<AccountMenu />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(container).toBeEmptyDOMElement();
  });

  it("offers a login link that carries the current path on 401", async () => {
    fetchReturning(reply({ detail: "需要先登录。" }, 401));
    render(<AccountMenu />);

    const link = await screen.findByRole("link", { name: /登录/ });
    expect(link).toHaveAttribute(
      "href",
      "/login?next=%2Fdiagnose%2FS_1",
    );
  });

  it("shows the display name and sends the cookie on mount", async () => {
    const fetchMock = fetchReturning(reply(OWNER));
    render(<AccountMenu />);

    expect(await screen.findByText("小林")).toBeInTheDocument();
    expect(screen.getByText("owner@example.com")).toBeInTheDocument();

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/auth/me");
    expect(init).toMatchObject({ credentials: "include" });
  });

  it("falls back to the email when there is no display name", async () => {
    fetchReturning(reply({ ...OWNER, display_name: null }));
    render(<AccountMenu />);

    expect(await screen.findByText("owner@example.com")).toBeInTheDocument();
  });

  it("logs out through the API and returns to the homepage", async () => {
    const fetchMock = fetchReturning(reply(OWNER), reply({ status: "ok" }));
    const user = userEvent.setup();
    render(<AccountMenu />);

    await user.click(await screen.findByRole("button", { name: "退出" }));

    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/"));
    expect(mocks.refresh).toHaveBeenCalled();
    const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toContain("/api/v1/auth/logout");
    expect(init).toMatchObject({ method: "POST", credentials: "include" });
    expect(screen.queryByText("小林")).not.toBeInTheDocument();
  });

  it("keeps the account visible when logout fails", async () => {
    fetchReturning(reply(OWNER), reply({ detail: "账号服务暂不可用。" }, 503));
    const user = userEvent.setup();
    render(<AccountMenu />);

    await user.click(await screen.findByRole("button", { name: "退出" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("退出失败");
    expect(screen.getByText("小林")).toBeInTheDocument();
    expect(mocks.replace).not.toHaveBeenCalled();
  });

  it("hides itself on the login page", async () => {
    mocks.pathname = "/login";
    const fetchMock = fetchReturning(reply(OWNER));
    const { container } = render(<AccountMenu />);

    expect(container).toBeEmptyDOMElement();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});