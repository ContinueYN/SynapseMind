import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  deleteModelSettings,
  getMe,
  getModelSettings,
  isAuthDisabled,
  isSessionReused,
  isUnauthorized,
  loginAccount,
  logoutAccount,
  requestCoach,
  SESSION_REUSED_EVENT,
  saveModelSettings,
  testModelSettings,
} from "./client";
import type {
  AuthUser,
  CoachResult,
  ModelSettings,
  ModelSettingsTestResult,
} from "./types";

const OWNER: AuthUser = {
  id: "U_OWNER",
  email: "owner@example.com",
  display_name: "小林",
  created_at: "2026-11-02T08:00:00+00:00",
};

const SETTINGS: ModelSettings = {
  configured: true,
  provider: "deepseek",
  base_url: "https://api.deepseek.com/v1",
  model: "deepseek-chat",
  key_last4: "abcd",
  last_verified_at: "2026-11-02T08:00:00+00:00",
  encryption_ready: true,
  warning: null,
};

const TEST_RESULT: ModelSettingsTestResult = {
  ok: true,
  latency_ms: 320,
  model: "deepseek-chat",
  message: "连接成功。",
};

function reply(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => (body === undefined ? "" : JSON.stringify(body)),
  } as Response;
}

function stubFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolved, rejected) => {
    resolve = resolved;
    reject = rejected;
  });
  return { promise, resolve, reject };
}

describe("auth client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends the HttpOnly cookie on /auth/me and parses the account", async () => {
    const fetchMock = stubFetch(reply(OWNER));

    await expect(getMe()).resolves.toEqual(OWNER);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/v1\/auth\/me$/);
    expect(init.credentials).toBe("include");
  });

  it("classifies 401 as logged out and 403 as auth disabled", async () => {
    stubFetch(reply({ detail: "需要先登录。" }, 401));
    const unauthorized = await getMe().catch((error: unknown) => error);
    expect(unauthorized).toBeInstanceOf(ApiError);
    expect(isUnauthorized(unauthorized)).toBe(true);
    expect(isSessionReused(unauthorized)).toBe(false);
    expect(isAuthDisabled(unauthorized)).toBe(false);

    stubFetch(reply({ detail: "认证未启用。" }, 403));
    const disabled = await getMe().catch((error: unknown) => error);
    expect(isAuthDisabled(disabled)).toBe(true);
    expect(isUnauthorized(disabled)).toBe(false);
  });

  it("accepts an empty 204 logout response", async () => {
    const fetchMock = stubFetch(reply(undefined, 204));

    await expect(logoutAccount()).resolves.toBeUndefined();

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
  });

  it("surfaces the API detail string on a failed login", async () => {
    stubFetch(reply({ detail: "邮箱或密码不正确。" }, 401));

    await expect(
      loginAccount({ email: "owner@example.com", password: "password123" }),
    ).rejects.toMatchObject({
      status: 401,
      message: "邮箱或密码不正确。",
    });
  });

  it("posts the coach focus with the session cookie", async () => {
    const coach: CoachResult = {
      version: "0.1",
      mode: "rules",
      focus: "where_wrong",
      headline: "先不判对错：这段过程里有一处可以核对。",
      points: [
        {
          kind: "next_step",
          text: "补一句依据。",
          basis: "checklist[0]",
        },
      ],
      next_question: "依据是哪一条？",
      not_claimed: ["没有判断对错。"],
      disclaimer: "规则版：没有调用模型；这是过程反馈，不是解法。",
    };
    const fetchMock = stubFetch(reply(coach));

    await expect(requestCoach("S/1", "where_wrong")).resolves.toEqual(coach);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/v1\/sessions\/S%2F1\/coach$/);
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ focus: "where_wrong" }));
    expect(init.credentials).toBe("include");
  });
});

describe("model settings client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("reads, saves, tests and deletes with the session cookie", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(reply(SETTINGS))
      .mockResolvedValueOnce(reply({ ...SETTINGS, key_last4: "wxyz" }))
      .mockResolvedValueOnce(reply(TEST_RESULT))
      .mockResolvedValueOnce(reply(undefined, 204));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getModelSettings()).resolves.toEqual(SETTINGS);
    await expect(
      saveModelSettings({
        provider: "deepseek",
        base_url: "https://api.deepseek.com/v1",
        model: "deepseek-chat",
        api_key: "sk-test-1234abcd",
      }),
    ).resolves.toEqual({ ...SETTINGS, key_last4: "wxyz" });
    await expect(testModelSettings({ provider: "deepseek" })).resolves.toEqual(
      TEST_RESULT,
    );
    await expect(deleteModelSettings()).resolves.toBeUndefined();

    const calls = fetchMock.mock.calls as [string, RequestInit][];
    expect(calls[0][0]).toMatch(/\/api\/v1\/settings\/model$/);
    expect(calls[0][1].credentials).toBe("include");
    expect(calls[1][0]).toMatch(/\/api\/v1\/settings\/model$/);
    expect(calls[1][1]).toMatchObject({
      method: "PUT",
      credentials: "include",
    });
    expect(JSON.parse(String(calls[1][1].body))).toEqual({
      provider: "deepseek",
      base_url: "https://api.deepseek.com/v1",
      model: "deepseek-chat",
      api_key: "sk-test-1234abcd",
    });
    expect(calls[2][0]).toMatch(/\/api\/v1\/settings\/model\/test$/);
    expect(calls[2][1]).toMatchObject({
      method: "POST",
      credentials: "include",
    });
    expect(JSON.parse(String(calls[2][1].body))).toEqual({
      provider: "deepseek",
    });
    expect(calls[3][0]).toMatch(/\/api\/v1\/settings\/model$/);
    expect(calls[3][1]).toMatchObject({
      method: "DELETE",
      credentials: "include",
    });
  });

  it("lets a failed request settle before starting the next one", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(reply({ detail: "需要先登录。" }, 401))
      .mockResolvedValueOnce(reply(OWNER));
    vi.stubGlobal("fetch", fetchMock);

    const failed = getMe().catch((error: unknown) => error);
    const next = getMe();

    const caught = await failed;
    expect(isUnauthorized(caught)).toBe(true);
    await expect(next).resolves.toEqual(OWNER);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("authenticated request queue", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("starts the second concurrent call only after the first one resolves", async () => {
    const first = deferred<Response>();
    const second = deferred<Response>();
    const order: string[] = [];
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => {
        order.push("first:start");
        return first.promise;
      })
      .mockImplementationOnce(() => {
        order.push("second:start");
        return second.promise;
      });
    vi.stubGlobal("fetch", fetchMock);

    const firstCall = getMe().then((user) => {
      order.push("first:done");
      return user;
    });
    const secondCall = getMe().then((user) => {
      order.push("second:done");
      return user;
    });

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(order).toEqual(["first:start"]);

    first.resolve(reply(OWNER));
    await firstCall;
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(order).toEqual(["first:start", "first:done", "second:start"]);

    second.resolve(reply(OWNER));
    await secondCall;
    expect(order).toEqual([
      "first:start",
      "first:done",
      "second:start",
      "second:done",
    ]);
  });
});

describe("session reuse", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("flags a replayed-cookie 401 and tells the account UI", async () => {
    stubFetch(reply({ detail: "会话被复用，已强制退出。" }, 401));
    const listener = vi.fn();
    window.addEventListener(SESSION_REUSED_EVENT, listener);
    try {
      const caught = await getMe().catch((error: unknown) => error);
      expect(isSessionReused(caught)).toBe(true);
      expect(isUnauthorized(caught)).toBe(true);
      expect(listener).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener(SESSION_REUSED_EVENT, listener);
    }
  });
});