"use client";

import { useEffect, useState } from "react";

import { searchKnowledge } from "@/src/lib/api/client";
import type { KnowledgeHit, KnowledgeSearch } from "@/src/lib/api/types";

const KIND_LABEL: Record<KnowledgeHit["kind"], string> = {
  concept: "概念",
  pattern: "模式",
  method: "方法",
  error: "常见错误",
  source: "来源",
};

/**
 * Sourced concept explanations beside a diagnosis card.
 *
 * It is deliberately separate from the card: retrieval cannot change the
 * diagnosis, and a missing RAG runtime only hides this panel. The query is the
 * card label, never the student's answer or work.
 */
export function KnowledgePanel({
  query,
  subject,
  verification,
}: {
  query: string;
  subject?: string;
  verification?: string;
}) {
  const [result, setResult] = useState<KnowledgeSearch | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setResult(null);
    setFailed(false);
    const cleaned = query.trim();
    if (!cleaned) return;

    const filter = subject?.trim();
    const mode = verification?.trim();
    searchKnowledge(cleaned, {
      subject: filter ? filter : undefined,
      verification: mode ? mode : undefined,
    })
      .then((data) => {
        if (!cancelled) setResult(data);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });

    return () => {
      cancelled = true;
    };
  }, [query, subject, verification]);

  const hits = result?.hits ?? [];
  if (failed || !result?.enabled || hits.length === 0) return null;

  return (
    <section aria-label="相关知识点" className="sm-knowledge">
      <p className="sm-kicker">相关知识点</p>
      <p className="sm-knowledge-note">
        来自公开教材的概念解释，不是对你这次作答的判断。
      </p>
      <ul>
        {hits.map((hit) => (
          <li key={hit.card_id}>
            <h3>
              <span className="sm-knowledge-kind">{KIND_LABEL[hit.kind]}</span>
              {hit.title}
            </h3>
            <p>{hit.excerpt}</p>
            <p className="sm-knowledge-source">
              <a href={hit.source.url} rel="noreferrer" target="_blank">
                {hit.source.title}
              </a>
              <span> · {hit.source.license}</span>
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}