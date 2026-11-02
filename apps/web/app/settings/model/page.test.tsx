import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ModelSettingsPage from "./page";
import type { ModelSettings } from "@/src/lib/api/types";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

const UNCONFIGURED: ModelSettings = {
  configured: false,
  provider: "deepseek",
  base_url: "",
  model: "",
  key_last4: null,
  last_verified_at: null,
  encryption_ready: true,
  warning: null,
};

const CONFIGURED: ModelSettings = {
  configured: true,
  provider: "deepseek",
  base_url: "https://api.deepseek.com/v1",
  model: "deepseek-chat",
  key_last4: "abcd",
  last_verified_at: "2026-11-02T08:00:00+00:00",
  encryption_ready: true,
  warning: null,
};

function reply(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => (body === undefined ? "" : JSON.stringify(body)),
  } as Response;
}

function fetchQueue(...responses: Response[]) {
  const fetchMock = vi.fn();
  for (const response of responses) fetchMock.mockResolvedValueOnce(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("ModelSettingsPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the saved provider, endpoint and masked key", async () => {
    fetchQueue(reply(CONFIGURED));
    render(<ModelSettingsPage />);

    expect(
      await screen.findByText("这个账号已经配置模型。"),
    ).toBeInTheDocument();
    expect(screen.getByText("sk-••••abcd")).toBeInTheDocument();
    expect(screen.getByText("https://api.deepseek.com/v1")).toBeInTheDocument();
    expect(screen.getByText("deepseek-chat")).toBeInTheDocument();
    expect(screen.getByLabelText("Provider")).toHaveValue("deepseek");
    expect(screen.getByLabelText(/API Key/)).toHaveValue("");
    expect(screen.getByText(/还没有验证过|2026/)).toBeInTheDocument();
  });

  it("prefills a provider preset and keeps the custom endpoint editable", async () => {
    fetchQueue(reply(UNCONFIGURED));
    const user = userEvent.setup();
    render(<ModelSettingsPage />);
    await screen.findByText("这个账号还没有配置模型。");

    const provider = screen.getByLabelText("Provider");
    await user.selectOptions(provider, "openai");
    expect(screen.getByLabelText("Base URL")).toHaveValue(
      "https://api.openai.com/v1",
    );
    expect(screen.getByLabelText("模型")).toHaveValue("gpt-4o-mini");

    await user.selectOptions(provider, "custom");
    // 自定义保留当前值，方便在已有端点上改，而不是清空
    expect(screen.getByLabelText("Base URL")).toHaveValue(
      "https://api.openai.com/v1",
    );
  });

  it("saves with a typed key, masks it and clears the input", async () => {
    const fetchMock = fetchQueue(
      reply(UNCONFIGURED),
      reply({ ...CONFIGURED, key_last4: "7xyz" }),
    );
    const user = userEvent.setup();
    render(<ModelSettingsPage />);
    await screen.findByText("这个账号还没有配置模型。");

    await user.clear(screen.getByLabelText("Base URL"));
    await user.type(
      screen.getByLabelText("Base URL"),
      "https://api.deepseek.com/v1",
    );
    await user.clear(screen.getByLabelText("模型"));
    await user.type(screen.getByLabelText("模型"), "deepseek-chat");

    const keyInput = screen.getByLabelText(/API Key/);
    await user.type(keyInput, "sk-test-1234abcd");
    await user.click(screen.getByRole("button", { name: "保存" }));

    expect(
      await screen.findByText("已保存。页面上只保留 Key 的末四位。"),
    ).toBeInTheDocument();
    expect(screen.getByText("sk-••••7xyz")).toBeInTheDocument();
    expect(keyInput).toHaveValue("");
    expect(document.body.textContent).not.toContain("sk-test-1234abcd");
    expect(fetchMock).toHaveBeenCalledTimes(2);

    const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toMatch(/\/api\/v1\/settings\/model$/);
    expect(init).toMatchObject({ method: "PUT", credentials: "include" });
    expect(JSON.parse(String(init.body))).toEqual({
      provider: "deepseek",
      base_url: "https://api.deepseek.com/v1",
      model: "deepseek-chat",
      api_key: "sk-test-1234abcd",
    });
  });

  it("tests the typed values and reports latency plus the sanitized message", async () => {
    const fetchMock = fetchQueue(
      reply(UNCONFIGURED),
      reply({
        ok: true,
        latency_ms: 321,
        model: "deepseek-chat",
        message: "连接成功。",
      }),
    );
    const user = userEvent.setup();
    render(<ModelSettingsPage />);
    await screen.findByText("这个账号还没有配置模型。");

    await user.type(screen.getByLabelText(/API Key/), "sk-test-abcd9999");
    await user.click(screen.getByRole("button", { name: "测试连接" }));

    const result = await screen.findByRole("status");
    expect(result).toHaveTextContent("连接可用");
    expect(result).toHaveTextContent("321 ms");
    expect(result).toHaveTextContent("连接成功");
    expect(result).not.toHaveTextContent("sk-test-abcd9999");

    const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toMatch(/\/api\/v1\/settings\/model\/test$/);
    expect(init).toMatchObject({ method: "POST", credentials: "include" });
    expect(JSON.parse(String(init.body))).toEqual({
      provider: "deepseek",
      base_url: "https://api.deepseek.com/v1",
      model: "deepseek-chat",
      api_key: "sk-test-abcd9999",
    });
  });

  it("shows a provider rejection as ok:false without treating it as a crash", async () => {
    fetchQueue(
      reply(UNCONFIGURED),
      reply({
        ok: false,
        latency_ms: null,
        model: null,
        message: "鉴权失败：Key 被拒绝。",
      }),
    );
    const user = userEvent.setup();
    render(<ModelSettingsPage />);
    await screen.findByText("这个账号还没有配置模型。");

    await user.click(screen.getByRole("button", { name: "测试连接" }));

    const result = await screen.findByRole("alert");
    expect(result).toHaveTextContent("连接失败");
    expect(result).toHaveTextContent("鉴权失败：Key 被拒绝。");
  });

  it("warns when the server has no credential master key", async () => {
    fetchQueue(reply({ ...CONFIGURED, encryption_ready: false }));
    render(<ModelSettingsPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "服务端未配置 SYNAPSE_CREDENTIAL_KEY，暂时不能保存 Key",
    );
  });

  it("turns a 503 from save into the same actionable warning", async () => {
    fetchQueue(
      reply(CONFIGURED),
      reply({ detail: "服务端缺少凭据密钥。" }, 503),
    );
    const user = userEvent.setup();
    render(<ModelSettingsPage />);
    await screen.findByText("这个账号已经配置模型。");

    await user.type(screen.getByLabelText(/API Key/), "sk-test-abcd0000");
    await user.click(screen.getByRole("button", { name: "保存" }));

    const alerts = await screen.findAllByRole("alert");
    const text = alerts.map((node) => node.textContent ?? "").join(" ");
    expect(text).toContain(
      "服务端未配置 SYNAPSE_CREDENTIAL_KEY，暂时不能保存 Key",
    );
  });

  it("deletes the saved key and returns to the unconfigured state", async () => {
    const fetchMock = fetchQueue(reply(CONFIGURED), reply(undefined, 204));
    const user = userEvent.setup();
    render(<ModelSettingsPage />);
    await screen.findByText("这个账号已经配置模型。");

    await user.click(screen.getByRole("button", { name: "删除 Key" }));

    expect(await screen.findByText(/已删除保存的 Key/)).toBeInTheDocument();
    expect(screen.getByText("这个账号还没有配置模型。")).toBeInTheDocument();
    expect(screen.queryByText("sk-••••abcd")).not.toBeInTheDocument();

    const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toMatch(/\/api\/v1\/settings\/model$/);
    expect(init).toMatchObject({ method: "DELETE", credentials: "include" });
  });

  it("asks a signed-out visitor to sign in and come back here", async () => {
    fetchQueue(reply({ detail: "需要先登录。" }, 401));
    render(<ModelSettingsPage />);

    const link = await screen.findByRole("link", { name: /去登录/ });
    expect(link).toHaveAttribute(
      "href",
      "/login?next=%2Fsettings%2Fmodel",
    );
  });

  it("explains a forced logout when the session cookie was replayed", async () => {
    fetchQueue(reply({ detail: "会话被复用，已强制退出。" }, 401));
    render(<ModelSettingsPage />);

    expect(
      await screen.findByText("检测到会话被复用，已强制退出。"),
    ).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /重新登录/ });
    expect(link).toHaveAttribute(
      "href",
      "/login?reason=session_reused&next=%2Fsettings%2Fmodel",
    );
  });

  it("explains that a deployment without accounts cannot store a key", async () => {
    fetchQueue(reply({ detail: "认证未启用。" }, 403));
    render(<ModelSettingsPage />);

    expect(
      await screen.findByText("这个部署没有开启账号。"),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /回交题页/ })).toHaveAttribute(
      "href",
      "/",
    );
  });
});