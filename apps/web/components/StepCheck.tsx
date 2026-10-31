"use client";

import { FormEvent, useState } from "react";

import { Surface } from "@/components/Surface";
import { StepVerdictView } from "@/components/StepVerdictView";
import { verifyStep } from "@/src/lib/api/client";
import type { StepVerdict } from "@/src/lib/api/types";

/**
 * 单步检查：只回答「这个等号成不成立」。
 *
 * 它是只读动作——不推进对话、不生成卡点卡，也不把 `unknown` 说成正确。
 * 这个组件只给数学用（一行等式）；物理走需要结构化载荷的
 * `PhysicsStepCheck`，语文没有可自动验证的真值，不摆这个入口。
 */

const STATUS_COPY: Record<
  StepVerdict["status"],
  { tag: string; badge: string; caveat: string }
> = {
  fail: {
    tag: "这个等号不成立",
    badge: "有反例",
    caveat: "只否定这一个等号，不代表整道题都错。",
  },
  unknown: {
    tag: "这一步没判出来",
    badge: "未证明",
    caveat: "没判出来不等于这一步正确；系统只检查它能读懂的等号。",
  },
  pass: {
    tag: "没发现不一致",
    badge: "未证明",
    caveat: "只说明检查过的部分没有矛盾，不是整步证明。",
  },
};

interface StepCheckProps {
  sessionId: string;
}

export function StepCheck({ sessionId }: StepCheckProps) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [verdict, setVerdict] = useState<StepVerdict | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const step = text.trim();
    if (!step || busy) return;

    setBusy(true);
    setError(null);
    setVerdict(null);
    try {
      setVerdict(await verifyStep(sessionId, { text: step, node_id: "" }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "检查失败，请重试。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="sm-stepcheck">
      <button
        aria-controls="sm-stepcheck-panel"
        aria-expanded={open}
        className="sm-stepcheck-toggle"
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <span>
          有一步拿不准？
          <small>只查等号 · 不推进对话</small>
        </span>
        <i>{open ? "收起" : "看一下"}</i>
      </button>

      {open ? (
        <Surface className="sm-stepcheck-panel" id="sm-stepcheck-panel">
          <p className="sm-kicker">单步检查</p>
          <h2 className="sm-h2">贴一行你写的式子。</h2>
          <p className="sm-p">
            系统只做一件事：看等号两边是不是真的相等。读不懂的写法会被跳过，不猜。
          </p>

          <form onSubmit={submit}>
            <label className="sm-f">
              <span className="sm-f-label">这一步</span>
              <textarea
                disabled={busy}
                onChange={(event) => {
                  setText(event.target.value);
                  setVerdict(null);
                }}
                placeholder="例如：sin(x)/(x+sin(x)/cos(x)) = sin(x)/x + cos(x)"
                rows={3}
                value={text}
              />
            </label>

            <div className="sm-stepcheck-actions">
              <button
                className="sm-cta"
                disabled={busy || !text.trim()}
                type="submit"
              >
                {busy ? "正在检查" : "检查这一步"}
                <span aria-hidden="true" className="sm-ar">
                  →
                </span>
              </button>
              <span className="sm-stepcheck-aside">
                赋值、定义和读不懂的式子会跳过；只判断这一步，不判断整道题。
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