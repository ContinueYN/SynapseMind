"use client";

import Link from "next/link";

import { Surface } from "@/components/Surface";
import type { DomainIntake } from "@/src/lib/api/types";

/**
 * 通用入口视图：没有参考结构时的唯一输出。
 *
 * 它不是卡点卡的简化版，而是**另一种承诺**：这一轮没建图，所以不定位卡点、
 * 不估把握、不给唯一答案。它只交代三件事——按哪个领域处理、这一轮要核对什么、
 * 下一步给什么。领域判断把握为 0 时不显示百分比，避免把“猜不出”包装成精度。
 */

const MODE_LABEL: Record<DomainIntake["domain"]["verification"], string> = {
  formal: "形式验证",
  executable: "可执行验证",
  empirical: "经验验证",
  argumentative: "论证结构",
};

interface IntakeViewProps {
  intake: DomainIntake;
  sessionId: string;
}

export function IntakeView({ intake, sessionId }: IntakeViewProps) {
  const domain = intake.domain;
  const mode = MODE_LABEL[domain.verification];
  const confidence = Math.round(domain.confidence * 100);

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

        {intake.clarifier ? (
          <p className="sm-note" style={{ marginTop: 16 }}>
            {intake.clarifier}
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