"use client";

import Link from "next/link";
import { useState } from "react";

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

  return (
    <article className="diagnosis-card">
      <header className="diagnosis-head">
        <p className="eyebrow">卡点卡 · {card.layer}</p>
        <h1>{card.label}</h1>
        <p className="diagnosis-line">{card.one_line}</p>
        <div className="badge-row">
          <span className={`confidence-badge ${card.confidence_label}`}>
            {CONFIDENCE_LABEL[card.confidence_label]} {Math.round(card.confidence * 100)}%
          </span>
          <span className="soft-badge">对应节点 {card.node_id}</span>
        </div>
      </header>

      <section className="card-section">
        <h2>证据</h2>
        <ul>
          {card.evidence.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </section>

      <section className="card-section">
        <h2>已排除</h2>
        <ul>
          {card.excluded.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </section>

      <section className="next-action">
        <p className="eyebrow">
          下一步 · {card.next_action.duration_min ?? 3} 分钟
        </p>
        <h2>{card.next_action.type === "micro_lesson" ? "只讲一个点" : "再补一个例子"}</h2>
        <p>
          先补“{card.label}”对应的最小动作，再做一道同构题；24 小时后用新题验证，
          而不是马上刷更多同类题。
        </p>
        <div className="next-actions">
          {showCardLink ? (
            <Link className="primary-link" href={`/card/${sessionId}`}>
              打开完整卡点卡
            </Link>
          ) : null}
          <button
            className="text-button quiet"
            onClick={() => setDisagreed(true)}
            type="button"
          >
            {disagreed ? "已记录，等待复核" : "我不同意这个判断"}
          </button>
        </div>
      </section>
    </article>
  );
}