"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { GlassCard, shineGlass } from "@/components/GlassCard";
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
  const wrapRef = useRef<HTMLDivElement>(null);

  const minutes = card.next_action.duration_min ?? 3;
  const dueHours = card.verify?.due_hours ?? 24;
  const excluded = card.excluded ?? [];
  const confidence = Math.round((card.confidence ?? 0) * 100);

  /* 卡一出现，一块玻璃被光扫过——这是"定位到了"的仪式感 */
  useEffect(() => {
    const el = wrapRef.current?.querySelector<HTMLElement>(".sm-glass");
    if (el) shineGlass(el);
  }, [card.node_id]);

  return (
    <div ref={wrapRef}>
      <GlassCard>
        <p className="sm-verdict-lab">
          卡点 · {CONFIDENCE_LABEL[card.confidence_label]} · {card.layer}
          <span className="sm-meter" title={`置信度 ${confidence}%`}>
            <i style={{ width: `${Math.min(100, Math.max(6, confidence))}%` }} />
          </span>
        </p>

        <h2 className="sm-h2">{card.label}</h2>
        <p className="sm-vsub">{card.one_line}</p>

        <dl className="sm-rows">
          {card.evidence.map((item, index) => (
            <div className="sm-row" key={item}>
              <dt>{String(index + 1).padStart(2, "0")}</dt>
              <dd>{item}</dd>
            </div>
          ))}
        </dl>

        <p className="sm-fine">每条依据都来自你自己的原话或原步骤，不改写、不推断。</p>

        {excluded.length > 0 ? (
          <p className="sm-excl">
            <b>已排除</b>　{excluded.join(" · ")}
          </p>
        ) : null}

        <div className="sm-act3">
          <div>
            <div className="sm-ch">即刻 · {minutes} 分钟</div>
            <p>只补「{card.label}」对应的最小动作，不重做整道题。</p>
          </div>
          <div>
            <div className="sm-ch">同构题 · 1 道</div>
            <p>
              {card.next_action.type === "micro_lesson"
                ? "换一道同结构题，只写关键几步，不必算完。"
                : "再补一个同类型的例子，只写关键几步。"}
            </p>
          </div>
          <div>
            <div className="sm-ch">验证 · {dueHours} 小时后</div>
            <p>一道新题，检查这个动作有没有变成习惯。不刷同类题。</p>
          </div>
        </div>

        <div className="sm-card-acts">
          {showCardLink ? (
            <Link className="sm-act" href={`/card/${sessionId}`}>
              打开完整卡点卡
              <span aria-hidden="true" className="sm-ar">
                →
              </span>
            </Link>
          ) : null}
          <button className="sm-bail" onClick={() => setDisagreed(true)} type="button">
            {disagreed ? "已记录，等待复核" : "我不同意这个判断"}
          </button>
        </div>

        <p className="sm-fine">
          本记录仅用于教学定位：不产出能力分数，不做智力或医学评估，不给提分承诺。
        </p>
      </GlassCard>
    </div>
  );
}