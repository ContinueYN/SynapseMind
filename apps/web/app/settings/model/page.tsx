"use client";

import Link from "next/link";
import {
  ChangeEvent,
  FormEvent,
  useCallback,
  useEffect,
  useState,
} from "react";

import { Plane } from "@/components/Plane";
import { SignInRequired } from "@/components/SignInRequired";
import { Surface } from "@/components/Surface";
import {
  ApiError,
  deleteModelSettings,
  getModelSettings,
  isAuthDisabled,
  isSessionReused,
  isUnauthorized,
  saveModelSettings,
  testModelSettings,
} from "@/src/lib/api/client";
import type {
  ModelSettings,
  ModelSettingsTestResult,
  TestModelSettingsInput,
} from "@/src/lib/api/types";

type ProviderKey = "deepseek" | "openai" | "openrouter" | "custom";
type Phase =
  | "loading"
  | "ready"
  | "signed_out"
  | "session_reused"
  | "unavailable"
  | "error";
type Activity = "save" | "test" | "delete" | null;

interface ProviderPreset {
  value: ProviderKey;
  label: string;
  baseUrl: string;
  model: string;
}

const PRESETS: ProviderPreset[] = [
  {
    value: "deepseek",
    label: "DeepSeek",
    baseUrl: "https://api.deepseek.com/v1",
    model: "deepseek-chat",
  },
  {
    value: "openai",
    label: "OpenAI",
    baseUrl: "https://api.openai.com/v1",
    model: "gpt-4o-mini",
  },
  {
    value: "openrouter",
    label: "OpenRouter",
    baseUrl: "https://openrouter.ai/api/v1",
    model: "openai/gpt-4o-mini",
  },
  {
    value: "custom",
    label: "自定义 OpenAI 兼容",
    baseUrl: "",
    model: "",
  },
];

const SETTINGS_PATH = "/settings/model";
const KEY_WARNING = "服务端未配置 SYNAPSE_CREDENTIAL_KEY，暂时不能保存 Key。";

function presetFor(provider: string): ProviderPreset | null {
  return PRESETS.find((preset) => preset.value === provider) ?? null;
}

function providerKey(provider: string): ProviderKey {
  return PRESETS.some((preset) => preset.value === provider)
    ? (provider as ProviderKey)
    : "custom";
}

function maskedKey(last4: string | null): string {
  return last4 ? `sk-••••${last4}` : "未保存";
}

function formatVerified(value: string | null): string {
  if (!value) return "还没有验证过";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * The server should never echo the key. This is a second belt: if a provider
 * error happens to quote the request body, the typed key is replaced before it
 * reaches the DOM. Nothing here is ever logged.
 */
function redactSecret(message: string, typedKey: string): string {
  const secret = typedKey.trim();
  return secret.length >= 4 ? message.split(secret).join("sk-••••") : message;
}

function authPhase(caught: unknown): Phase | null {
  if (isSessionReused(caught)) return "session_reused";
  if (isUnauthorized(caught)) return "signed_out";
  if (isAuthDisabled(caught)) return "unavailable";
  return null;
}

export default function ModelSettingsPage() {
  const [phase, setPhase] = useState<Phase>("loading");
  const [settings, setSettings] = useState<ModelSettings | null>(null);
  const [provider, setProvider] = useState<ProviderKey>("deepseek");
  const [baseUrl, setBaseUrl] = useState(PRESETS[0].baseUrl);
  const [model, setModel] = useState(PRESETS[0].model);
  const [apiKey, setApiKey] = useState("");
  const [keyWarning, setKeyWarning] = useState<string | null>(null);
  const [activity, setActivity] = useState<Activity>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<ModelSettingsTestResult | null>(
    null,
  );

  const applySettings = useCallback((next: ModelSettings) => {
    setSettings(next);
    setKeyWarning(next.encryption_ready ? null : KEY_WARNING);
    const key = providerKey(next.provider);
    const preset = presetFor(key);
    setProvider(key);
    // A blank field means "not configured yet": show the preset instead of an
    // empty box. `custom` has no preset, so the saved values stay as-is.
    setBaseUrl(next.base_url || preset?.baseUrl || "");
    setModel(next.model || preset?.model || "");
    // The key itself is never returned, so the input starts empty every time.
    setApiKey("");
  }, []);

  const load = useCallback(async () => {
    setPhase("loading");
    setError(null);
    setNotice(null);
    setTestResult(null);
    try {
      const next = await getModelSettings();
      applySettings(next);
      setPhase("ready");
    } catch (caught) {
      const auth = authPhase(caught);
      if (auth) {
        setSettings(null);
        setApiKey("");
        setPhase(auth);
        return;
      }
      setError(
        caught instanceof Error && caught.message
          ? caught.message
          : "读取模型设置失败，请稍后重试。",
      );
      setPhase("error");
    }
  }, [applySettings]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleFailure = useCallback((caught: unknown, fallback: string) => {
    const auth = authPhase(caught);
    if (auth) {
      setSettings(null);
      setApiKey("");
      setPhase(auth);
      return;
    }
    if (caught instanceof ApiError && caught.status === 503) {
      setKeyWarning(KEY_WARNING);
      setError(
        caught.message && caught.message !== KEY_WARNING
          ? `${KEY_WARNING}（${caught.message}）`
          : KEY_WARNING,
      );
      return;
    }
    setError(
      caught instanceof Error && caught.message ? caught.message : fallback,
    );
  }, []);

  function chooseProvider(event: ChangeEvent<HTMLSelectElement>) {
    const next = event.target.value as ProviderKey;
    setProvider(next);
    const preset = presetFor(next);
    // `custom` keeps whatever the user already has: they need to type an
    // OpenAI-compatible endpoint by hand, and blanking it would lose context.
    if (preset && next !== "custom") {
      setBaseUrl(preset.baseUrl);
      setModel(preset.model);
    }
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (activity) return;

    const cleanKey = apiKey.trim();
    if (!cleanKey) {
      setError("保存需要重新输入 API Key；已保存的 Key 不会显示在页面上。");
      return;
    }
    if (!baseUrl.trim()) {
      setError("请填写 Base URL。");
      return;
    }
    if (!model.trim()) {
      setError("请填写模型名。");
      return;
    }

    setActivity("save");
    setError(null);
    setNotice(null);
    setTestResult(null);
    try {
      const saved = await saveModelSettings({
        provider,
        base_url: baseUrl.trim(),
        model: model.trim(),
        api_key: cleanKey,
      });
      applySettings(saved);
      setNotice("已保存。页面上只保留 Key 的末四位。");
    } catch (caught) {
      handleFailure(caught, "保存失败，请稍后重试。");
    } finally {
      setActivity(null);
    }
  }

  async function test() {
    if (activity) return;
    setActivity("test");
    setError(null);
    setNotice(null);
    setTestResult(null);
    const input: TestModelSettingsInput = {
      provider,
      base_url: baseUrl.trim(),
      model: model.trim(),
    };
    const cleanKey = apiKey.trim();
    // No typed key means "use the saved one"; the server decides whether it
    // has one, and answers `ok:false` honestly when it does not.
    if (cleanKey) input.api_key = cleanKey;
    try {
      setTestResult(await testModelSettings(input));
    } catch (caught) {
      handleFailure(caught, "测试失败，请稍后重试。");
    } finally {
      setActivity(null);
    }
  }

  async function removeKey() {
    if (activity) return;
    setActivity("delete");
    setError(null);
    setNotice(null);
    setTestResult(null);
    try {
      await deleteModelSettings();
      setSettings((current) =>
        current
          ? {
              ...current,
              configured: false,
              key_last4: null,
              last_verified_at: null,
              warning: null,
            }
          : current,
      );
      setApiKey("");
      setNotice("已删除保存的 Key。表单里的地址与模型还在，重新填写 Key 后可以再保存。");
    } catch (caught) {
      handleFailure(caught, "删除失败，请稍后重试。");
    } finally {
      setActivity(null);
    }
  }

  if (phase === "loading") {
    return (
      <section className="sm-state sm-page">
        <Plane>
          <p className="sm-kicker">模型设置</p>
          <h1 className="sm-h1">正在读取这个账号的模型配置。</h1>
        </Plane>
      </section>
    );
  }

  if (phase === "signed_out") {
    return <SignInRequired next={SETTINGS_PATH} />;
  }

  if (phase === "session_reused") {
    return (
      <section className="sm-state sm-page">
        <Plane>
          <p className="sm-kicker">会话已退出</p>
          <h1 className="sm-h1">检测到会话被复用，已强制退出。</h1>
          <p className="sm-p">
            这是安全机制：同一份登录凭据被重复使用时，服务端会作废旧会话。
            请重新登录后再改模型设置。当前页面不会保留你填过的 Key。
          </p>
          <p style={{ marginTop: 26 }}>
            <Link
              className="sm-cta"
              href={`/login?reason=session_reused&next=${encodeURIComponent(SETTINGS_PATH)}`}
            >
              重新登录
              <span aria-hidden="true" className="sm-ar">
                →
              </span>
            </Link>
          </p>
        </Plane>
      </section>
    );
  }

  if (phase === "unavailable") {
    return (
      <section className="sm-state sm-page">
        <Plane>
          <p className="sm-kicker">模型设置</p>
          <h1 className="sm-h1">这个部署没有开启账号。</h1>
          <p className="sm-p">
            模型 Key 保存在具体账号下；没有账号层时这里不可用。诊断本身不受影响。
          </p>
          <p style={{ marginTop: 26 }}>
            <Link className="sm-cta" href="/">
              回交题页
              <span aria-hidden="true" className="sm-ar">
                →
              </span>
            </Link>
          </p>
        </Plane>
      </section>
    );
  }

  if (phase === "error") {
    return (
      <section className="sm-state sm-page">
        <Plane>
          <p className="sm-kicker">读取失败</p>
          <h1 className="sm-h1">没有读到模型设置。</h1>
          <p className="sm-p" role="alert">
            {error}
          </p>
          <p style={{ marginTop: 26 }}>
            <button className="sm-cta" onClick={() => void load()} type="button">
              重试
              <span aria-hidden="true" className="sm-ar">
                →
              </span>
            </button>
          </p>
        </Plane>
      </section>
    );
  }

  const configured = settings?.configured ?? false;
  const last4 = settings?.key_last4 ?? null;

  return (
    <div className="sm-settings sm-page">
      <header className="sm-settings-head">
        <p className="sm-eyebrow">
          <span aria-hidden="true" className="sm-dot" />
          账号 · 模型设置
        </p>
        <h1 className="sm-h1 sm-settings-title">用你自己的模型账号。</h1>
        <p className="sm-lede sm-settings-lede">
          每个账号单独保存 Provider、Base URL、模型和 API Key。Key 在服务端加密保存，
          页面只回显末四位；换掉或删除后，旧 Key 不再生效。
        </p>
      </header>

      <Surface className="sm-settings-panel">
        <p className="sm-kicker">当前状态</p>
        <h2 className="sm-h2">
          {configured ? "这个账号已经配置模型。" : "这个账号还没有配置模型。"}
        </h2>
        <dl className="sm-settings-facts">
          <div>
            <dt>状态</dt>
            <dd>{configured ? "已配置" : "未配置"}</dd>
          </div>
          <div>
            <dt>Provider</dt>
            <dd>{settings?.provider || "—"}</dd>
          </div>
          <div>
            <dt>API Key</dt>
            <dd>{maskedKey(last4)}</dd>
          </div>
          <div>
            <dt>Base URL</dt>
            <dd className="sm-settings-break">{settings?.base_url || "—"}</dd>
          </div>
          <div>
            <dt>模型</dt>
            <dd className="sm-settings-break">{settings?.model || "—"}</dd>
          </div>
          <div>
            <dt>上次验证</dt>
            <dd>{formatVerified(settings?.last_verified_at ?? null)}</dd>
          </div>
        </dl>

        {keyWarning ? (
          <p className="sm-alert" role="alert">
            {keyWarning} 请让运维设置该环境变量后重试。
          </p>
        ) : null}
        {settings?.warning ? (
          <p className="sm-settings-hint" role="status">
            {settings.warning}
          </p>
        ) : null}
      </Surface>

      <Surface className="sm-settings-panel">
        <p className="sm-kicker">配置</p>
        <h2 className="sm-h2">
          {configured ? "替换 Provider 或 Key。" : "填入你的 Provider 与 Key。"}
        </h2>

        <form
          aria-busy={activity !== null}
          className="sm-form sm-settings-form"
          noValidate
          onSubmit={save}
        >
          <div className="sm-f">
            <label className="sm-f-label" htmlFor="model-provider">
              Provider
            </label>
            <select
              id="model-provider"
              name="provider"
              onChange={chooseProvider}
              value={provider}
            >
              {PRESETS.map((preset) => (
                <option key={preset.value} value={preset.value}>
                  {preset.label}
                </option>
              ))}
            </select>
          </div>

          <div className="sm-settings-grid">
            <div className="sm-f">
              <label className="sm-f-label" htmlFor="model-base-url">
                Base URL
              </label>
              <input
                autoComplete="url"
                id="model-base-url"
                inputMode="url"
                name="base_url"
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder="https://api.deepseek.com/v1"
                type="url"
                value={baseUrl}
              />
            </div>

            <div className="sm-f">
              <label className="sm-f-label" htmlFor="model-name">
                模型
              </label>
              <input
                autoComplete="off"
                id="model-name"
                name="model"
                onChange={(event) => setModel(event.target.value)}
                placeholder="deepseek-chat"
                type="text"
                value={model}
              />
            </div>
          </div>

          <div className="sm-f">
            <label className="sm-f-label" htmlFor="model-api-key">
              API Key
              <em>
                {last4
                  ? `已保存 ${maskedKey(last4)}；保存需重新输入`
                  : "必填，只保存到服务端"}
              </em>
            </label>
            <input
              autoComplete="off"
              id="model-api-key"
              name="api_key"
              onChange={(event) => setApiKey(event.target.value)}
              placeholder={last4 ? "输入新 Key 以替换" : "sk-…"}
              type="password"
              value={apiKey}
            />
          </div>

          {error ? (
            <p className="sm-alert" role="alert">
              {error}
            </p>
          ) : null}
          {notice ? (
            <p className="sm-settings-ok" role="status">
              {notice}
            </p>
          ) : null}
          {testResult ? (
            <p
              className={
                testResult.ok
                  ? "sm-settings-result"
                  : "sm-settings-result sm-settings-result-fail"
              }
              role={testResult.ok ? "status" : "alert"}
            >
              <b>{testResult.ok ? "连接可用" : "连接失败"}</b>
              {testResult.latency_ms !== null
                ? ` · ${testResult.latency_ms} ms`
                : ""}
              {testResult.model ? ` · ${testResult.model}` : ""}
              <span>：{redactSecret(testResult.message, apiKey)}</span>
            </p>
          ) : null}

          <div className="sm-settings-actions">
            <button
              className="sm-cta sm-settings-save"
              disabled={activity !== null}
              type="submit"
            >
              {activity === "save" ? "保存中" : "保存"}
              <span aria-hidden="true" className="sm-ar">
                →
              </span>
            </button>
            <button
              className="sm-btn"
              disabled={activity !== null}
              onClick={test}
              type="button"
            >
              {activity === "test" ? "测试中" : "测试连接"}
            </button>
            <button
              className="sm-btn sm-btn-danger"
              disabled={activity !== null || !configured}
              onClick={removeKey}
              type="button"
            >
              {activity === "delete" ? "删除中" : "删除 Key"}
            </button>
          </div>
        </form>

        <p className="sm-fine">
          测试会真的请求一次 Provider；失败只说明这次请求没成，不代表 Key
          一定错。Key 不会显示在页面或浏览器存储里。
        </p>
      </Surface>
    </div>
  );
}