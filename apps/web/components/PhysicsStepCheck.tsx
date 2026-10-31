"use client";

import { FormEvent, useState } from "react";

import { Surface } from "@/components/Surface";
import { StepVerdictView } from "@/components/StepVerdictView";
import { buildPhysicsStepPayload } from "@/components/physics-step";
import { verifyStep } from "@/src/lib/api/client";
import type { StepVerdict } from "@/src/lib/api/types";

const STATUS_COPY: Record<
  StepVerdict["status"],
  { tag: string; badge: string; caveat: string }
> = {
  fail: {
    tag: "这一步有矛盾",
    badge: "有矛盾",
    caveat: "只否定检查到的量纲或数值关系，不代表整道题都错。",
  },
  unknown: {
    tag: "这一步没判出来",
    badge: "未证明",
    caveat: "缺单位、缺数值或读不懂，都不等于这一步正确；系统不猜单位。",
  },
  pass: {
    tag: "没发现不一致",
    badge: "已检查",
    caveat: "只说明跑过的量纲/回代检查没有矛盾，不是整步证明。",
  },
};

interface PhysicsStepCheckProps {
  sessionId: string;
}

/**
 * Physics step check: units first, numeric replay when values are supplied.
 *
 * The dialogue stays untouched. Empty values means only the dimension check
 * runs, and the server's detail says so explicitly.
 */
export function PhysicsStepCheck({ sessionId }: PhysicsStepCheckProps) {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState("");
  const [unit, setUnit] = useState("");
  const [unitsText, setUnitsText] = useState("");
  const [valuesText, setValuesText] = useState("");
  const [expectedText, setExpectedText] = useState("");
  const [toleranceText, setToleranceText] = useState("");
  const [absoluteToleranceText, setAbsoluteToleranceText] = useState("");
  const [busy, setBusy] = useState(false);
  const [verdict, setVerdict] = useState<StepVerdict | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;

    const payload = buildPhysicsStepPayload({
      step,
      unit,
      unitsText,
      valuesText,
      expectedText,
      toleranceText,
      absoluteToleranceText,
    });
    if ("error" in payload) {
      setVerdict(null);
      setError(payload.error);
      return;
    }

    setBusy(true);
    setError(null);
    setVerdict(null);
    try {
      setVerdict(
        await verifyStep(sessionId, {
          text: payload.text,
          node_id: "",
          data: payload.data,
        }),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "检查失败，请重试。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="sm-stepcheck">
      <button
        aria-controls="sm-physics-stepcheck-panel"
        aria-expanded={open}
        className="sm-stepcheck-toggle"
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <span>
          有一步拿不准？
          <small>查量纲 / 数值回代 · 不推进对话</small>
        </span>
        <i>{open ? "收起" : "看一下"}</i>
      </button>

      {open ? (
        <Surface className="sm-stepcheck-panel" id="sm-physics-stepcheck-panel">
          <p className="sm-kicker">物理单步检查</p>
          <h2 className="sm-h2">把这一步写成等式。</h2>
          <p className="sm-p">
            系统先看两边量纲，再在你填了数值时回代；填了结果时，还会把等式右边或表达式的值和你写的答案比。读不懂、缺单位或缺数值时返回「没判出来」，不猜。
          </p>

          <form onSubmit={submit}>
            <label className="sm-f">
              <span className="sm-f-label">
                这一步
                <em>等式或一个量</em>
              </span>
              <textarea
                aria-label="这一步"
                disabled={busy}
                onChange={(event) => {
                  setStep(event.target.value);
                  setVerdict(null);
                }}
                placeholder="例如：F - mu*N = m*a"
                rows={3}
                value={step}
              />
            </label>

            <div className="sm-stepcheck-grid">
              <label className="sm-f">
                <span className="sm-f-label">
                  符号单位
                  <em>每行 符号=单位</em>
                </span>
                <textarea
                  aria-label="符号单位"
                  disabled={busy}
                  onChange={(event) => {
                    setUnitsText(event.target.value);
                    setVerdict(null);
                  }}
                  placeholder={"F=N\nm=kg\na=m/s^2\nmu="}
                  rows={4}
                  value={unitsText}
                />
              </label>

              <label className="sm-f">
                <span className="sm-f-label">
                  数值
                  <em>可选，按左列单位</em>
                </span>
                <textarea
                  aria-label="数值"
                  disabled={busy}
                  onChange={(event) => {
                    setValuesText(event.target.value);
                    setVerdict(null);
                  }}
                  placeholder={"F=10\nm=2\na=3\nmu=0.2"}
                  rows={4}
                  value={valuesText}
                />
              </label>
            </div>

            <label className="sm-f">
              <span className="sm-f-label">
                结果单位
                <em>只写一个量或声明结果时必填</em>
              </span>
              <input
                aria-label="结果单位"
                disabled={busy}
                onChange={(event) => {
                  setUnit(event.target.value);
                  setVerdict(null);
                }}
                placeholder="例如：N"
                type="text"
                value={unit}
              />
            </label>

            <div className="sm-stepcheck-grid sm-stepcheck-grid--wide-first">
              <label className="sm-f">
                <span className="sm-f-label">
                  你写的结果
                  <em>可选，和右边/表达式的值比对</em>
                </span>
                <input
                  aria-label="你写的结果"
                  disabled={busy}
                  inputMode="decimal"
                  onChange={(event) => {
                    setExpectedText(event.target.value);
                    setVerdict(null);
                  }}
                  placeholder="例如：6"
                  type="text"
                  value={expectedText}
                />
              </label>

              <label className="sm-f">
                <span className="sm-f-label">
                  相对容差
                  <em>%，可选</em>
                </span>
                <input
                  aria-label="相对容差"
                  disabled={busy}
                  inputMode="decimal"
                  onChange={(event) => {
                    setToleranceText(event.target.value);
                    setVerdict(null);
                  }}
                  placeholder="例如：1"
                  type="text"
                  value={toleranceText}
                />
              </label>

              <label className="sm-f">
                <span className="sm-f-label">
                  绝对容差
                  <em>和结果单位相同，可选</em>
                </span>
                <input
                  aria-label="绝对容差"
                  disabled={busy}
                  inputMode="decimal"
                  onChange={(event) => {
                    setAbsoluteToleranceText(event.target.value);
                    setVerdict(null);
                  }}
                  placeholder="例如：0.05"
                  type="text"
                  value={absoluteToleranceText}
                />
              </label>
            </div>

            <div className="sm-stepcheck-actions">
              <button
                className="sm-cta"
                disabled={busy || !step.trim()}
                type="submit"
              >
                {busy ? "正在检查" : "检查这一步"}
                <span aria-hidden="true" className="sm-ar">
                  →
                </span>
              </button>
              <span className="sm-stepcheck-aside">
                单位写成 m=kg、a=m/s^2；无量纲写 mu=。没填数值时只做量纲检查；容差 1 表示 1%，绝对容差和结果单位相同；两项都填时同时生效，只填一项时另一项用默认。
              </span>
            </div>
          </form>

          {error ? (
            <p className="sm-alert" role="alert">
              {error}
            </p>
          ) : null}

          {verdict ? (
            <StepVerdictView copy={STATUS_COPY} verdict={verdict} />
          ) : null}
        </Surface>
      ) : null}
    </section>
  );
}