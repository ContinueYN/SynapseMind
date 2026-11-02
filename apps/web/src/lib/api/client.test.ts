import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  getMe,
  isAuthDisabled,
  isUnauthorized,
  loginAccount,
  logoutAccount,
  requestCoach,
} from "./client";
import type { AuthUser, CoachResult } from "./types";

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

function stubFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
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