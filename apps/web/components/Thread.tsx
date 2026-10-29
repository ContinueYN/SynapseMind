import type { CSSProperties } from "react";

import type { HistoryItem } from "@/src/lib/api/types";

interface ThreadProps {
  items: HistoryItem[];
  /** 刚点下的答案：先落进线索里，等后端回话 */
  pending?: { answer: string; unknown: boolean } | null;
  /** 指针停在哪一轮：左轨上对应的节点跟着亮 */
  hotTurn?: number | null;
  onHoverTurn?: (turn: number | null) => void;
}

/**
 * 问答是一条连续的线，不是一张被整块换掉的卡。
 * 已经答过的问句留在原地（变淡，但不消失），这样用户能看见“我在第几层”。
 */
export function Thread({ items, pending = null, hotTurn = null, onHoverTurn }: ThreadProps) {
  if (items.length === 0 && !pending) return null;

  return (
    <ol className="sm-thread">
      {items.map((item, row) => (
        <li
          className="sm-tl"
          data-done="true"
          data-hot={hotTurn === item.turn ? "true" : undefined}
          data-unknown={item.is_unknown}
          key={`${item.turn}-${item.question}`}
          onMouseEnter={() => onHoverTurn?.(item.turn)}
          onMouseLeave={() => onHoverTurn?.(null)}
          style={{ "--i": row } as CSSProperties}
        >
          <span aria-hidden="true" className="sm-tl-n" />
          <p className="sm-tl-q">{item.question}</p>
          <p className="sm-tl-a">
            <b>{item.is_unknown ? "我答" : "你答"}</b>
            <span>{item.answer}</span>
          </p>
        </li>
      ))}

      {pending ? (
        <li className="sm-tl" data-done="false" data-pending="true">
          <span aria-hidden="true" className="sm-tl-n" />
          <p className="sm-tl-q">（正在读你这一句）</p>
          <p className="sm-tl-a">
            <b>你答</b>
            <span>{pending.unknown ? "我不知道" : pending.answer}</span>
          </p>
        </li>
      ) : null}
    </ol>
  );
}