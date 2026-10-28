import type { HistoryItem } from "@/src/lib/api/types";

export function Transcript({ items }: { items: HistoryItem[] }) {
  if (items.length === 0) {
    return null;
  }
  return (
    <section className="transcript" aria-label="对话记录">
      <h2>刚才的对话</h2>
      <ol>
        {items.map((item) => (
          <li key={`${item.turn}-${item.question}`}>
            <p className="transcript-question">{item.question}</p>
            <p className="transcript-answer">
              {item.is_unknown ? "我不知道" : item.answer}
            </p>
          </li>
        ))}
      </ol>
    </section>
  );
}