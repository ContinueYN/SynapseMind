"use client";

import Link from "next/link";

import { Surface } from "@/components/Surface";
import type { StructureHint } from "@/src/lib/api/types";

/**
 * 结构提示：NONE 档学科的唯一输出。
 *
 * 它不是卡点卡的简化版，而是**另一种承诺**：只列出参考结构的步骤，标出
 * 学生过程里“写到 / 只写到一部分 / 没看到”的步骤，指一下下一步先看哪里。
 * 没有层级、没有把握百分比、没有“你卡在这里”的句子——那些需要可证伪的证据。
 *
 * 所以这里刻意不给卡片式的结论，也不复用 `DiagnosisCardView` 的尺与层级。
 */

const SUBJECT_LABEL: Record<string, string> = {
  chinese: "语文",
  english: "英语",
  history: "历史",
};

interface StructureHintViewProps {
  hint: StructureHint;
  sessionId: string;
}

export function StructureHintView({ hint, sessionId }: StructureHintViewProps) {
  const steps = hint.steps ?? [];
  const covered = steps.filter((step) => step.status === "covered").length;
  const partial = steps.filter((step) => step.status === "partial").length;
  const touched = covered + partial;
  const focus = steps.find((step) => step.node_id === hint.focus_node_id);
  const subject = SUBJECT_LABEL[hint.subject] ?? hint.subject;

  return (
    <Surface>
      <div className="sm-card">
        <div className="sm-card-head">
          <div className="sm-card-lab">
            <b>结构提示 · 不定位卡点</b>
            <span>
              {subject} · 这一步只对照结构，不判断对错
            </span>
          </div>

          <div
            aria-label={`${steps.length} 步中有 ${touched} 步写到或写到了一部分`}
            className="sm-hint-tally"
            role="img"
          >
            <b>
              {touched}
              <i>/ {steps.length}</i>
            </b>
            <span>有写到的步数（含部分）</span>
          </div>
        </div>

        <h2 className="sm-card-h">
          {focus ? `下一步先看「${focus.text}」` : "每一步都提到了"}
        </h2>
        <p className="sm-card-sub">{hint.one_line}</p>

        <p className="sm-lab" style={{ marginTop: 30 }}>
          参考步骤
        </p>
        <ol className="sm-steps">
          {steps.map((step, index) => (
            <li
              data-focus={step.node_id === hint.focus_node_id ? "true" : undefined}
              data-status={step.status}
              key={step.node_id}
            >
              <b>{String(index + 1).padStart(2, "0")}</b>
              <span>{step.text}</span>
              <i>
                {step.status === "covered"
                  ? "已写到"
                  : step.status === "partial"
                    ? "写到了一部分"
                    : "没看到"}
              </i>
            </li>
          ))}
        </ol>

        <p className="sm-fine" style={{ marginTop: 18 }}>
          {hint.next_step}
        </p>

        <p className="sm-note sm-note-quiet" style={{ marginTop: 16 }}>
          {hint.disclaimer}
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