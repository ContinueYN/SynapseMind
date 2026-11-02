"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";

import { Plane } from "@/components/Plane";
import {
  ApiError,
  isAuthDisabled,
  isSessionReused,
  isUnauthorized,
  loginAccount,
  registerAccount,
} from "@/src/lib/api/client";

type Mode = "login" | "register";

/**
 * Only same-site paths are accepted as a post-login target. A `next` value
 * coming from a link could otherwise be turned into an open redirect.
 */
function safeNext(value: string | null): string {
  if (!value) return "/";
  if (!value.startsWith("/") || value.startsWith("//")) return "/";
  // Browsers may normalize backslashes into slashes; do not allow `/\host`.
  if (value.includes("\\")) return "/";
  if (value === "/login" || value.startsWith("/login?") || value.startsWith("/login/")) {
    return "/";
  }
  return value;
}

function LoginPanel() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const target = safeNext(searchParams.get("next"));
  // AccountMenu and the 401 handler send `reason=session_reused`; accept a
  // bare `session` marker as well so an older link still explains itself.
  const sessionReused =
    searchParams.get("reason") === "session_reused" ||
    Boolean(searchParams.get("session"));

  function switchMode(next: Mode) {
    if (next === mode) return;
    setMode(next);
    setPassword("");
    setError(null);
  }

  function validate(): string | null {
    if (!email.trim()) return "请填写邮箱。";
    if (!email.includes("@")) return "邮箱格式看起来不对。";
    if (password.length < 8) return "密码至少 8 位。";
    return null;
  }

  function describe(caught: unknown): string {
    if (isAuthDisabled(caught)) {
      return "这个部署没有开启账号功能，不需要登录。";
    }
    if (isSessionReused(caught)) {
      return "检测到会话被复用，已强制退出，请重新登录。";
    }
    if (isUnauthorized(caught)) {
      // The API uses one message for an unknown email and a wrong password;
      // do not add a guess about which one it was.
      return "邮箱或密码不对。";
    }
    if (caught instanceof ApiError && caught.status === 409) {
      return "这个邮箱已经注册过了，请直接登录。";
    }
    if (caught instanceof ApiError && caught.status === 422) {
      return "邮箱或密码格式不符合要求。";
    }
    if (caught instanceof Error && caught.message) return caught.message;
    return "请求失败，请稍后重试。";
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;

    const local = validate();
    if (local) {
      setError(local);
      return;
    }

    setBusy(true);
    setError(null);
    try {
      if (mode === "login") {
        await loginAccount({ email: email.trim(), password });
      } else {
        const name = displayName.trim();
        await registerAccount({
          email: email.trim(),
          password,
          ...(name ? { display_name: name } : {}),
        });
      }
      router.replace(target);
    } catch (caught) {
      setError(describe(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="sm-auth sm-page">
      <header className="sm-auth-head">
        <p className="sm-eyebrow">
          <span aria-hidden="true" className="sm-dot" />
          账号 · HttpOnly cookie
        </p>
        <h1 className="sm-h1 sm-auth-title">
          {mode === "login" ? "回到你上次停下的地方。" : "创建一个账号。"}
        </h1>
        <p className="sm-lede sm-auth-lede">
          {mode === "login"
            ? "登录后可以继续未完成的诊断，并读取这个账号自己的模型设置。密码不保存在浏览器里，会话由服务端写入 HttpOnly cookie。"
            : "每个账号保存自己的诊断记录与模型设置。注册是否开放由这个部署的运维决定；同一个邮箱只能注册一次。"}
        </p>
      </header>

      <Plane className="sm-auth-panel">
        {sessionReused ? (
          <p className="sm-auth-notice" role="alert">
            检测到会话被复用，已强制退出，请重新登录。
          </p>
        ) : null}

        <div aria-label="登录或创建账号" className="sm-auth-tabs" role="tablist">
          <button
            aria-selected={mode === "login"}
            className="sm-auth-tab"
            onClick={() => switchMode("login")}
            role="tab"
            type="button"
          >
            登录
          </button>
          <button
            aria-selected={mode === "register"}
            className="sm-auth-tab"
            onClick={() => switchMode("register")}
            role="tab"
            type="button"
          >
            创建账号
          </button>
        </div>

        <form aria-busy={busy} className="sm-form" noValidate onSubmit={handleSubmit}>
          <label className="sm-f">
            <span className="sm-f-label">邮箱</span>
            <input
              autoComplete="email"
              autoFocus
              id="auth-email"
              inputMode="email"
              name="email"
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@example.com"
              type="email"
              value={email}
            />
          </label>

          <label className="sm-f">
            <span className="sm-f-label">
              密码 <em>至少 8 位</em>
            </span>
            <input
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              id="auth-password"
              name="password"
              onChange={(event) => setPassword(event.target.value)}
              placeholder={mode === "login" ? "输入密码" : "设置一个至少 8 位的密码"}
              type="password"
              value={password}
            />
          </label>

          {mode === "register" ? (
            <label className="sm-f">
              <span className="sm-f-label">
                显示名 <em>可选</em>
              </span>
              <input
                autoComplete="nickname"
                id="auth-display-name"
                name="display_name"
                onChange={(event) => setDisplayName(event.target.value)}
                placeholder="例如：小林"
                type="text"
                value={displayName}
              />
            </label>
          ) : null}

          {error ? (
            <p className="sm-alert" role="alert">
              {error}
            </p>
          ) : null}

          <div className="sm-auth-actions">
            <button className="sm-cta sm-auth-submit" disabled={busy} type="submit">
              {busy ? "请稍候" : mode === "login" ? "登录" : "创建账号"}
              <span aria-hidden="true" className="sm-ar">
                →
              </span>
            </button>
          </div>
        </form>

        <p className="sm-fine sm-auth-note">
          {mode === "login"
            ? "还没有账号？切到「创建账号」。"
            : "已经有账号？切回「登录」。"}
        </p>

        <p className="sm-fine sm-auth-session">
          每次请求后会话 cookie 都会轮换；同一份凭据被重复使用时，会自动退出以保护账号。
        </p>

        <p className="sm-fine sm-auth-back">
          <Link className="sm-link sm-link-quiet" href="/">
            先不登录，回交题页
            <span aria-hidden="true" className="sm-ar">
              →
            </span>
          </Link>
        </p>
      </Plane>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <section className="sm-state">
          <Plane>
            <p className="sm-kicker">登录</p>
            <h1 className="sm-h1">正在准备账号页。</h1>
          </Plane>
        </section>
      }
    >
      <LoginPanel />
    </Suspense>
  );
}