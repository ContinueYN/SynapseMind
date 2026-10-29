import type { HistoryItem } from "@/src/lib/api/types";

/**
 * 诊断记录：默认折成一行，展开是逐条问答。
 * 用原生 details，不需要额外状态。
 */
export function Transcript({ items }: { items: HistoryItem[] }) {
  if (items.length === 0) {
    return null;
  }

  return (
    <details className="sm-trace">
      <summary>
        逐步记录
        <span className="sm-trace-meta">{items.length} 轮 · 展开</span>
      </summary>
      <ol className="sm-trace-list">
        {items.map((item) => (
          <li key={`${item.turn}-${item.question}`}>
            <b>第 {item.turn} 轮</b>
            {item.question}
            {" → "}
            {item.is_unknown ? "我不知道" : item.answer}
          </li>
        ))}
      </ol>
    </details>
  );
}