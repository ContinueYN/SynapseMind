import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import LoginPage from "./page";
import type { AuthUser } from "@/src/lib/api/types";

const mocks = vi.hoisted(() => ({
  next: "/",
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mocks.replace }),
  useSearchParams: () => new URLSearchParams(`next=${encodeURIComponent(mocks.next)}`),
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

function fetchReturning(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function fillLogin(email = "owner@example.com", password = "password123") {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("邮箱"), email);
  await user.type(screen.getByLabelText(/密码/), password);
  return user;
}

describe("LoginPage", () => {
  beforeEach(() => {
    mocks.next = "/";
    mocks.replace.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("starts on login and exposes the first-owner register copy", async () => {
    fetchReturning(reply(OWNER));
    const user = userEvent.setup();
    render(<LoginPage />);

    expect(screen.getByRole("tab", { name: "登录" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.queryByLabelText(/显示名/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "创建第一个账号" }));

    expect(screen.getByRole("tab", { name: "创建第一个账号" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByLabelText(/显示名/)).toBeInTheDocument();
    expect(screen.getByText(/第一个账号是拥有者账号/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /创建账号/ }),
    ).toBeInTheDocument();
  });

  it("validates email and an 8-character password before calling the API", async () => {
    fetchReturning(reply(OWNER));
    const user = userEvent.setup();
    render(<LoginPage />);

    await user.click(screen.getByRole("button", { name: /登录/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("请填写邮箱");

    await user.type(screen.getByLabelText("邮箱"), "owner@example.com");
    await user.click(screen.getByRole("button", { name: /登录/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("密码至少 8 位");

    expect(fetch).not.toHaveBeenCalled();
    expect(mocks.replace).not.toHaveBeenCalled();
  });

  it("logs in, sends the cookie, and replaces with the next path", async () => {
    mocks.next = "/diagnose/S_1";
    const fetchMock = fetchReturning(reply(OWNER));
    render(<LoginPage />);

    const user = await fillLogin();
    await user.click(screen.getByRole("button", { name: /登录/ }));

    await waitFor(() =>
      expect(mocks.replace).toHaveBeenCalledWith("/diagnose/S_1"),
    );
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/auth/login");
    expect(init).toMatchObject({ method: "POST", credentials: "include" });
    expect(JSON.parse(String(init.body))).toEqual({
      email: "owner@example.com",
      password: "password123",
    });
  });

  it("registers with an optional display name and starts on the homepage", async () => {
    const fetchMock = fetchReturning(reply(OWNER, 201));
    const user = userEvent.setup();
    render(<LoginPage />);

    await user.click(screen.getByRole("tab", { name: "创建第一个账号" }));
    await user.type(screen.getByLabelText("邮箱"), "owner@example.com");
    await user.type(screen.getByLabelText(/密码/), "password123");
    await user.type(screen.getByLabelText(/显示名/), "小林");
    await user.click(screen.getByRole("button", { name: /创建账号/ }));

    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/"));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/auth/register");
    expect(JSON.parse(String(init.body))).toEqual({
      email: "owner@example.com",
      password: "password123",
      display_name: "小林",
    });
  });

  it("does not turn a 401 into an account-existence hint", async () => {
    fetchReturning(reply({ detail: "邮箱或密码不正确。" }, 401));
    render(<LoginPage />);

    const user = await fillLogin();
    await user.click(screen.getByRole("button", { name: /登录/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("邮箱或密码不对。");
    expect(screen.queryByText(/不存在/)).not.toBeInTheDocument();
    expect(screen.queryByText(/没注册/)).not.toBeInTheDocument();
    expect(mocks.replace).not.toHaveBeenCalled();
  });

  it("explains a 403 as auth being disabled", async () => {
    fetchReturning(reply({ detail: "认证未启用。" }, 403));
    render(<LoginPage />);

    const user = await fillLogin();
    await user.click(screen.getByRole("button", { name: /登录/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "没有开启账号功能",
    );
  });

  it("rejects an external next target", async () => {
    mocks.next = "//evil.example.com/steal";
    fetchReturning(reply(OWNER));
    render(<LoginPage />);

    const user = await fillLogin();
    await user.click(screen.getByRole("button", { name: /登录/ }));

    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/"));
    expect(mocks.replace).not.toHaveBeenCalledWith("//evil.example.com/steal");
  });
});