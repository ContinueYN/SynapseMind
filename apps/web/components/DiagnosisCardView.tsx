"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Surface } from "@/components/Surface";
import type { DiagnosisCard } from "@/src/lib/api/types";

interface DiagnosisCardViewProps {
  card: DiagnosisCard;
  sessionId: string;
  showCardLink?: boolean;
}

const CONFIDENCE_LABEL = {
  high: "高置信",
  medium: "中置信",
  low: "低置信",
} as const;

export function DiagnosisCardView({
  card,
  sessionId,
  showCardLink = true,
}: DiagnosisCardViewProps) {
  const [disagreed, setDisagreed] = useState(false);
  const [shown, setShown] = useState(0);

  const minutes = card.next_action.duration_min ?? 3;
  const dueHours = card.verify?.due_hours ?? 24;
  const excluded = card.excluded ?? [];
  const confidence = Math.round((card.confidence ?? 0) * 100);

  /* 数字和尺上的刻线一起走到位：只看结论的人不该被一个跳变惊一下 */
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setShown(confidence);
      return;
    }
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / 560);
      setShown(Math.round(confidence * (1 - Math.pow(1 - progress, 3))));
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [confidence]);

  return (
    <Surface>
      <div className="sm-card">
        <div className="sm-card-head">
          <div className="sm-card-lab">
            <b>卡点 · {CONFIDENCE_LABEL[card.confidence_label]}</b>
            <span>
              层级 {card.layer} · 节点 {card.node_id}
            </span>
          </div>

          <div
            aria-label={`系统把握 ${confidence}%`}
            className="sm-scale"
            role="img"
          >
            <div className="sm-scale-top">
              <b className="sm-scale-v">
                {shown}
                <i>%</i>
              </b>
              <span className="sm-scale-lab">系统把握</span>
            </div>
            <div aria-hidden="true" className="sm-scale-track">
              <i style={{ width: `${shown}%` }} />
              <u style={{ left: `${shown}%` }} />
            </div>
          </div>
        </div>

          <h2 className="sm-card-h">{card.label}</h2>
          <p className="sm-card-sub">{card.one_line}</p>

          <p className="sm-lab" style={{ marginTop: 30 }}>
            依据你自己的话
          </p>
          <ol className="sm-ev">
            {card.evidence.map((item, index) => (
              <li key={item}>
                <b>{String(index + 1).padStart(2, "0")}</b>
                <span>{item}</span>
              </li>
            ))}
          </ol>
          <p className="sm-fine">不改写、不推断；每条都能回到那一轮的原文。</p>

          {excluded.length > 0 ? (
            <p className="sm-excl">
              <span className="sm-excl-k">已排除</span>
              {excluded.map((item) => (
                <span key={item}>{item}</span>
              ))}
            </p>
          ) : null}

          <div className="sm-plan">
            <div className="sm-plan-item">
              <span className="sm-ch">即刻 · {minutes} 分钟</span>
              <p>只补「{card.label}」对应的最小动作，不重做整道题。</p>
            </div>
            <div className="sm-plan-item">
              <span className="sm-ch">同构题 · 1 道</span>
              <p>
                {card.next_action.type === "micro_lesson"
                  ? "换一道同结构题，只写关键几步，不必算完。"
                  : "再补一个同类型的例子，只写关键几步。"}
              </p>
            </div>
            <div className="sm-plan-item">
              <span className="sm-ch">验证 · {dueHours} 小时后</span>
              <p>一道新题，检查这个动作有没有变成习惯。不刷同类题。</p>
            </div>
          </div>

          <div className="sm-card-foot">
            {showCardLink ? (
              <Link className="sm-cta" href={`/card/${sessionId}`}>
                打开完整卡点卡
                <span aria-hidden="true" className="sm-ar">
                  →
                </span>
              </Link>
            ) : null}
            <button
              className="sm-link sm-link-quiet"
              onClick={() => setDisagreed(true)}
              type="button"
            >
              {disagreed ? "已记录，等待复核" : "我不同意这个判断"}
            </button>
          </div>

          <p className="sm-fine">
            本记录仅用于教学定位：不产出能力分数，不做智力或医学评估，不给提分承诺。
          </p>
        </div>
    </Surface>
  );
}