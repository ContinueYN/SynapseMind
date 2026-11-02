"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { getMe, logoutAccount } from "@/src/lib/api/auth";
import {
  isAuthDisabled,
  isSessionReused,
  isUnauthorized,
  SESSION_REUSED_EVENT,
} from "@/src/lib/api/http";
import type { AuthUser } from "@/src/lib/api/types";

/**
 * 顶部右侧的账号入口。
 *
 * 三种回答分开处理，避免把「认证没开」误画成「你还没登录」：
 * - 200：显示简称与退出；
 * - 401：给一个去 /login 的小链接，并带上当前路径；
 * - 403（或网络失败）：什么都不画，保持原来的本地单人流程。
 *
 * 身份只存在 HttpOnly cookie 里，这里不缓存 token，也不写 localStorage。
 */
type AccountState =
  | { kind: "loading" }
  | { kind: "hidden" }
  | { kind: "signed_out"; reason?: "session_reused" }
  | { kind: "signed_in"; user: AuthUser };

function identity(user: AuthUser): string {
  return user.display_name?.trim() || user.email;
}

function shortIdentity(user: AuthUser): string {
  const raw = identity(user);
  return raw.length > 18 ? `${raw.slice(0, 17)}…` : raw;
}

function initial(user: AuthUser): string {
  const first = Array.from(identity(user).trim())[0];
  return first ? first.toUpperCase() : "?";
}

function loginHref(pathname: string | null, reason?: "session_reused"): string {
  const next = pathname && pathname !== "/" ? pathname : "/";
  const query = reason
    ? `reason=${reason}&next=${encodeURIComponent(next)}`
    : `next=${encodeURIComponent(next)}`;
  return `/login?${query}`;
}

export function AccountMenu() {
  const pathname = usePathname();
  const router = useRouter();
  const [state, setState] = useState<AccountState>({ kind: "loading" });
  const [leaving, setLeaving] = useState(false);
  const [logoutFailed, setLogoutFailed] = useState(false);

  useEffect(() => {
    // The login page hosts its own form; a second sign-in link there is noise.
    if (!pathname || pathname === "/login" || pathname.startsWith("/login/")) {
      setState({ kind: "hidden" });
      return;
    }

    let cancelled = false;
    getMe()
      .then((user) => {
        if (!cancelled) setState({ kind: "signed_in", user });
      })
      .catch((caught) => {
        if (cancelled) return;
        if (isAuthDisabled(caught)) {
          setState({ kind: "hidden" });
        } else if (isSessionReused(caught)) {
          setState({ kind: "signed_out", reason: "session_reused" });
        } else if (isUnauthorized(caught)) {
          setState({ kind: "signed_out" });
        } else {
          // API down or an older server without /auth/me: never invent a
          // login prompt. The rest of the page keeps its previous behavior.
          setState({ kind: "hidden" });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [pathname]);

  useEffect(() => {
    // A one-time login ticket was replayed somewhere else in the app. Drop the
    // identity immediately instead of waiting for the next /auth/me.
    function clearAccount() {
      if (!pathname || pathname === "/login" || pathname.startsWith("/login/")) {
        return;
      }
      setState({ kind: "signed_out", reason: "session_reused" });
    }

    window.addEventListener(SESSION_REUSED_EVENT, clearAccount);
    return () => window.removeEventListener(SESSION_REUSED_EVENT, clearAccount);
  }, [pathname]);

  async function signOut() {
    if (leaving) return;
    setLeaving(true);
    setLogoutFailed(false);
    try {
      await logoutAccount();
      setState({ kind: "hidden" });
      router.replace("/");
      router.refresh();
    } catch {
      setLogoutFailed(true);
    } finally {
      setLeaving(false);
    }
  }

  if (state.kind === "loading" || state.kind === "hidden") return null;

  if (state.kind === "signed_out") {
    return (
      <div className="sm-account">
        <Link
          className="sm-account-login"
          href={loginHref(pathname, state.reason)}
        >
          <span aria-hidden="true" className="sm-account-key">
            ↪
          </span>
          登录
        </Link>
      </div>
    );
  }

  const { user } = state;
  return (
    <div className="sm-account">
      <span
        className="sm-account-user"
        title={user.display_name ? `${user.display_name} · ${user.email}` : user.email}
      >
        <span aria-hidden="true" className="sm-account-avatar">
          {initial(user)}
        </span>
        <span className="sm-account-id">
          <span className="sm-account-name">{shortIdentity(user)}</span>
          {user.display_name ? (
            <span className="sm-account-mail">{user.email}</span>
          ) : null}
        </span>
        <Link className="sm-account-settings" href="/settings/model">
          模型设置
        </Link>
        <button
          className="sm-account-out"
          disabled={leaving}
          onClick={signOut}
          type="button"
        >
          {leaving ? "退出中" : "退出"}
        </button>
      </span>

      {logoutFailed ? (
        <span className="sm-account-error" role="alert">
          退出失败，请重试。
        </span>
      ) : null}
    </div>
  );
}