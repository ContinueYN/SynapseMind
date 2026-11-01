"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { Surface } from "@/components/Surface";
import type { DomainIntake } from "@/src/lib/api/types";

/**
 * 通用入口视图：没有参考结构时的唯一输出。
 *
 * 它不是卡点卡的简化版，而是**另一种承诺**：这一轮没建图，所以不定位卡点、
 * 不估把握、不给唯一答案。它只交代三件事——按哪个领域处理、这一轮要核对什么、
 * 下一步给什么。领域判断把握为 0 时不显示百分比，避免把“猜不出”包装成精度。
 *
 * v0.2 起会读学生自己交上来的那段话：先列出「看到了」哪几项，再列出「还缺」
 * 哪几项。两者都只说明有没有提到，不判断对错；没有作答时两段都不出现。
 *
 * v0.3 起还会显示一张通用结构图。它要么是模型整理的（来源标记为系统，未经
 * 人工审核），要么仍是从学生原话里抽的；两种都只说明「问题由什么组成」。
 * formal/empirical 检查只在真的跑了之后出现，`unknown` 一律写成「未检查」，
 * 不能读成通过。
 */

const MODE_LABEL: Record<DomainIntake["domain"]["verification"], string> = {
  formal: "形式验证",
  executable: "可执行验证",
  empirical: "经验验证",
  argumentative: "论证结构",
};

type IntakeNode = NonNullable<DomainIntake["graph"]>[number];
type IntakeCheck = NonNullable<DomainIntake["verifications"]>[number];

const NODE_LABEL: Record<IntakeNode["kind"], string> = {
  goal: "目标",
  given: "已知",
  constraint: "约束",
  assumption: "假设",
  plan: "计划",
  action: "动作",
  evidence: "证据",
  check: "核对",
  decision: "选项",
  risk: "风险",
  next: "下一步",
};

const CHECK_LABEL: Record<IntakeCheck["kind"], string> = {
  formal: "形式检查",
  empirical: "经验检查",
};

const CHECK_STATUS: Record<IntakeCheck["status"], string> = {
  pass: "未发现反例",
  fail: "发现不一致",
  unknown: "未检查",
};

interface IntakeViewProps {
  intake: DomainIntake;
  sessionId: string;
  notice?: string;
  busy?: boolean;
  /** When present, the single clarifying question becomes answerable once. */
  onClarify?: (answer: string) => Promise<void>;
}

export function IntakeView({
  intake,
  sessionId,
  notice,
  busy = false,
  onClarify,
}: IntakeViewProps) {
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const domain = intake.domain;
  const mode = MODE_LABEL[domain.verification];
  const confidence = Math.round(domain.confidence * 100);
  // Both fields are optional on the wire: a server older than v0.2 sends
  // neither, and the card then looks exactly like it did before.
  const observed = intake.observed ?? [];
  const gaps = intake.gaps ?? [];
  const graph = intake.graph ?? [];
  const verifications = intake.verifications ?? [];
  const origin = intake.origin ?? null;

  async function clarify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || !onClarify || sending || busy) return;
    setSending(true);
    try {
      await onClarify(text);
      setDraft("");
    } catch {
      // The parent surfaces the request error; keep the draft so it is not lost.
    } finally {
      setSending(false);
    }
  }

  return (
    <Surface>
      <div className="sm-card">
        <div className="sm-card-head">
          <div className="sm-card-lab">
            <b>入口整理 · 不定位卡点</b>
            <span>
              {domain.label} · {mode}
            </span>
          </div>

          <div
            aria-label={
              domain.confidence > 0
                ? `领域判断把握 ${confidence}%`
                : "没有判断出具体领域，按通用模式处理"
            }
            className="sm-hint-tally"
            role="img"
          >
            <b>{domain.confidence > 0 ? `${confidence}%` : "通用"}</b>
            <span>领域判断</span>
          </div>
        </div>

        <h2 className="sm-card-h">
          {domain.generic ? "这次先按通用问题处理" : `按「${domain.label}」处理`}
        </h2>
        <p className="sm-card-sub">{intake.one_line}</p>

        <p className="sm-lab" style={{ marginTop: 30 }}>
          这一轮先核对
        </p>
        <ol className="sm-steps">
          {intake.checklist.map((item, index) => (
            <li key={`${index}-${item}`}>
              <b>{String(index + 1).padStart(2, "0")}</b>
              <span>{item}</span>
              <i>{mode}</i>
            </li>
          ))}
        </ol>

        {observed.length > 0 ? (
          <p className="sm-fine" style={{ marginTop: 14 }}>
            你写的里面看到了：{observed.join("、")}。
          </p>
        ) : null}

        {gaps.length > 0 ? (
          <>
            <p className="sm-lab" style={{ marginTop: 22 }}>
              你写的里面还缺
            </p>
            {gaps.map((gap) => (
              <p
                className="sm-note sm-note-quiet"
                key={gap}
                style={{ marginTop: 8 }}
              >
                {gap}
              </p>
            ))}
          </>
        ) : null}

        {graph.length > 0 ? (
          <>
            <p className="sm-lab" style={{ marginTop: 22 }}>
              {origin === "system"
                ? "系统整理的结构"
                : "从你的话里整理的结构"}
            </p>
            <ul className="sm-steps">
              {graph.map((node, index) => (
                <li key={`${node.kind}-${index}-${node.text}`}>
                  <b>{NODE_LABEL[node.kind]}</b>
                  <span>{node.text}</span>
                  {origin === "system" ? <i>模型整理</i> : null}
                </li>
              ))}
            </ul>
            {origin === "system" ? (
              <p className="sm-fine" style={{ marginTop: 14 }}>
                它只说明问题由什么组成，不是诊断结论，也没有判断对错。
              </p>
            ) : null}
          </>
        ) : null}

        {verifications.length > 0 ? (
          <>
            <p className="sm-lab" style={{ marginTop: 22 }}>
              自动检查
            </p>
            {verifications.map((check) => (
              <p
                className={
                  check.status === "unknown"
                    ? "sm-fine"
                    : "sm-note sm-note-quiet"
                }
                key={check.kind}
                style={{ marginTop: 8 }}
              >
                <b>
                  {CHECK_LABEL[check.kind]} · {CHECK_STATUS[check.status]}
                </b>
                <span> {check.detail}</span>
              </p>
            ))}
          </>
        ) : null}

        {intake.clarifier ? (
          <>
            <p className="sm-note" style={{ marginTop: 16 }}>
              {intake.clarifier}
            </p>
            {onClarify ? (
              <form className="sm-form" onSubmit={clarify} style={{ marginTop: 16 }}>
                <label className="sm-f">
                  <span className="sm-f-label">补充一句</span>
                  <textarea
                    disabled={sending || busy}
                    maxLength={500}
                    onChange={(event) => setDraft(event.target.value)}
                    placeholder="用一句话回答上面的问题；不写也可以先离开"
                    rows={2}
                    value={draft}
                  />
                </label>
                <div className="sm-form-foot">
                  <button
                    className="sm-cta"
                    disabled={sending || busy || !draft.trim()}
                    type="submit"
                  >
                    {sending ? "正在并入" : "并入入口整理"}
                    <span aria-hidden="true" className="sm-ar">
                      →
                    </span>
                  </button>
                  <span className="sm-fine">只补充一次，仍然不定位卡点。</span>
                </div>
              </form>
            ) : null}
          </>
        ) : null}

        {notice ? (
          <p className="sm-note" role="status" style={{ marginTop: 16 }}>
            {notice}
          </p>
        ) : null}

        <p className="sm-fine" style={{ marginTop: 18 }}>
          {intake.next_step}
        </p>

        <p className="sm-note sm-note-quiet" style={{ marginTop: 16 }}>
          {intake.disclaimer}
        </p>

        <div className="sm-card-foot">
          <Link className="sm-cta" href="/" title={`会话 ${sessionId}`}>
            重新交一道题
            <span aria-hidden="true" className="sm-ar">
              →
            </span>
          </Link>
        </div>

        <p className="sm-fine">
          这一轮没有参考结构：不猜卡点、不给唯一答案、不产出能力分数。
        </p>
      </div>
    </Surface>
  );
}