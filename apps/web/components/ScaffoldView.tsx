"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { Surface } from "@/components/Surface";
import type { Scaffold } from "@/src/lib/api/types";

/**
 * 空白起步：先给 1–2 步示例，再让学生写下一行。
 *
 * 它不是提示卡，也不是卡点卡：不判断、不定位、不出现最终答案。提交后回到
 * 同一会话的追问链路，所以这里只需要一个自由文本框。
 */

interface ScaffoldViewProps {
  scaffold: Scaffold;
  sessionId: string;
  busy: boolean;
  onSubmit: (text: string) => void;
}

export function ScaffoldView({ scaffold, sessionId, busy, onSubmit }: ScaffoldViewProps) {
  const [text, setText] = useState("");
  const steps = scaffold.steps ?? [];

  useEffect(() => {
    setText("");
  }, [steps.length]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const clean = text.trim();
    if (!clean || busy) return;
    onSubmit(clean);
  }

  return (
    <Surface>
      <div className="sm-card">
        <div className="sm-card-head">
          <div className="sm-card-lab">
            <b>起步示例 · 先不定位</b>
            <span>没写过程时，先照着走一步再动笔</span>
          </div>
        </div>

        <h2 className="sm-card-h">先照着写一行，再开始追问</h2>
        <p className="sm-card-sub">
          示例只展示起步，不是本题答案。写下你现在的下一行，诊断会从这一行继续。
        </p>

        <p className="sm-lab" style={{ marginTop: 30 }}>
          参考起步
        </p>
        <ol className="sm-steps">
          {steps.map((step, index) => (
            <li data-status="covered" key={step.node_id ?? `step-${index}`}>
              <b>{String(index + 1).padStart(2, "0")}</b>
              <span>{step.text}</span>
              <i>示例</i>
            </li>
          ))}
        </ol>

        <p className="sm-fine" style={{ marginTop: 18 }}>
          {scaffold.next_step}
        </p>

        <form onSubmit={submit} style={{ marginTop: 20 }}>
          <label className="sm-f">
            <span className="sm-f-label">
              你的下一行 <em>写一行就行</em>
            </span>
            <textarea
              aria-label="你的下一行"
              onChange={(event) => setText(event.target.value)}
              placeholder="例如：定义域是 x>0；或者写出你想到的公式"
              rows={3}
              value={text}
            />
          </label>
          <button className="sm-cta" disabled={busy || !text.trim()} type="submit">
            {busy ? "正在接上…" : "写好了，继续诊断"}
            <span aria-hidden="true" className="sm-ar">
              →
            </span>
          </button>
        </form>

        <p className="sm-note sm-note-quiet" style={{ marginTop: 16 }}>
          {scaffold.disclaimer}
        </p>

        <div className="sm-card-foot">
          <Link className="sm-cta" href="/" title={`会话 ${sessionId}`}>
            换一道题
            <span aria-hidden="true" className="sm-ar">
              →
            </span>
          </Link>
        </div>

        <p className="sm-fine">
          本记录仅用于教学定位：不产出能力分数，不做智力或医学评估，不给提分承诺。
        </p>
      </div>
    </Surface>
  );
}