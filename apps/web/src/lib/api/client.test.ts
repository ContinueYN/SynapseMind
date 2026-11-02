import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
  searchKnowledge,
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

  it("accepts an empty 205 response too", async () => {
    stubFetch(reply(undefined, 205));

    await expect(logoutAccount()).resolves.toBeUndefined();
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

describe("login-ticket bootstrap", () => {
  beforeEach(async () => {
    // A protected response spends any ticket an earlier test left pending, so
    // every test starts with an open gate.
    stubFetch(reply(OWNER));
    await getMe();
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lets ordinary authenticated calls overlap once no ticket is pending", async () => {
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

    // Both fetches leave immediately; neither waits for the other response.
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(order).toEqual(["first:start", "second:start"]);

    first.resolve(reply(OWNER));
    second.resolve(reply(OWNER));
    await Promise.all([firstCall, secondCall]);

    expect(order.slice(0, 2)).toEqual(["first:start", "second:start"]);
    expect(order).toContain("first:done");
    expect(order).toContain("second:done");
  });

  it("serializes protected calls until the first post-login response spends the ticket", async () => {
    const first = deferred<Response>();
    const second = deferred<Response>();
    const third = deferred<Response>();
    const order: string[] = [];
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(reply(OWNER)) // login
      .mockImplementationOnce(() => {
        order.push("first:start");
        return first.promise;
      })
      .mockImplementationOnce(() => {
        order.push("second:start");
        return second.promise;
      })
      .mockImplementationOnce(() => {
        order.push("third:start");
        return third.promise;
      });
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      loginAccount({ email: OWNER.email, password: "password123" }),
    ).resolves.toEqual(OWNER);

    const firstCall = getMe().then((user) => {
      order.push("first:done");
      return user;
    });
    const secondCall = getModelSettings().then((settings) => {
      order.push("second:done");
      return settings;
    });

    // Only one ticket-consuming request is in flight before the first response.
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(order).toEqual(["first:start"]);

    first.resolve(reply(OWNER));
    await firstCall;
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(order).toEqual(["first:start", "first:done", "second:start"]);

    // The first response spent the ticket, so a new protected call is not held
    // behind the still-pending second one.
    const thirdCall = getMe().then((user) => {
      order.push("third:done");
      return user;
    });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    expect(order).toEqual([
      "first:start",
      "first:done",
      "second:start",
      "third:start",
    ]);

    second.resolve(reply(SETTINGS));
    third.resolve(reply(OWNER));
    await secondCall;
    await thirdCall;
  });

  it("never serializes public calls and never lets them spend the ticket", async () => {
    const publicCall = deferred<Response>();
    const firstProtected = deferred<Response>();
    const secondProtected = deferred<Response>();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(reply(OWNER)) // login
      .mockImplementationOnce(() => publicCall.promise)
      .mockImplementationOnce(() => firstProtected.promise)
      .mockImplementationOnce(() => secondProtected.promise);
    vi.stubGlobal("fetch", fetchMock);

    await loginAccount({ email: OWNER.email, password: "password123" });

    // A public call leaves immediately even while the ticket is pending.
    const knowledge = searchKnowledge("递归");
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    publicCall.resolve(reply({}));
    await knowledge;

    // Its response must not open the gate: the two protected calls below still
    // run one at a time.
    const protectedFirst = getMe();
    const protectedSecond = getModelSettings();
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));

    firstProtected.resolve(reply(OWNER));
    await protectedFirst;
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));

    secondProtected.resolve(reply(SETTINGS));
    await protectedSecond;
  });

  it("keeps the gate armed when a protected fetch fails before any response", async () => {
    const retry = deferred<Response>();
    const second = deferred<Response>();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(reply(OWNER)) // login
      .mockRejectedValueOnce(new Error("network down")) // getMe, no response
      .mockImplementationOnce(() => retry.promise)
      .mockImplementationOnce(() => second.promise);
    vi.stubGlobal("fetch", fetchMock);

    await loginAccount({ email: OWNER.email, password: "password123" });
    await expect(getMe()).rejects.toMatchObject({ status: 0 });

    // The failed call never reached the server, so the ticket may still be
    // valid: the next two protected calls remain serialized.
    const retried = getMe();
    const concurrent = getModelSettings();
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock).toHaveBeenCalledTimes(3);

    retry.resolve(reply(OWNER));
    await retried;
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));

    second.resolve(reply(SETTINGS));
    await concurrent;
  });
});

describe("session reuse", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("flags a replayed login-ticket 401 and tells the account UI", async () => {
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

describe("API_BASE", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("keeps an explicit empty value as same-origin and strips a trailing slash", async () => {
    vi.resetModules();
    vi.stubEnv("NEXT_PUBLIC_API_BASE", "https://api.example.test/");
    const absolute = await import("./client");
    expect(absolute.API_BASE).toBe("https://api.example.test");

    vi.resetModules();
    vi.stubEnv("NEXT_PUBLIC_API_BASE", "");
    const sameOrigin = await import("./client");
    expect(sameOrigin.API_BASE).toBe("");
  });
});