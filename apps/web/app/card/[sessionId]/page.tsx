"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { DiagnosisCardView } from "@/components/DiagnosisCardView";
import { getSession } from "@/src/lib/api/client";
import type { SessionResponse } from "@/src/lib/api/types";

export default function CardPage() {
  const params = useParams<{ sessionId: string }>();
  const sessionId = params.sessionId;
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSession(sessionId)
      .then(setSession)
      .catch((caught) =>
        setError(caught instanceof Error ? caught.message : "加载卡点卡失败。"),
      );
  }, [sessionId]);

  if (error) {
    return (
      <section className="state-panel">
        <h1>卡点卡没打开</h1>
        <p>{error}</p>
        <Link className="primary-link" href="/">
          回到交题页
        </Link>
      </section>
    );
  }

  if (!session) {
    return (
      <section className="state-panel">
        <p className="eyebrow">正在读取</p>
        <h1>把证据整理成一张卡。</h1>
      </section>
    );
  }

  if (!session.diagnosis) {
    return (
      <section className="state-panel">
        <h1>这次还没有卡点卡。</h1>
        <p>{session.notice ?? "追问还没收敛；先回到对话继续，或补一步过程。"}</p>
        <Link className="primary-link" href={`/diagnose/${sessionId}`}>
          回到对话
        </Link>
      </section>
    );
  }

  return (
    <div className="card-page">
      <Link className="back-link" href={`/diagnose/${sessionId}`}>
        ← 回到对话
      </Link>
      <DiagnosisCardView
        card={session.diagnosis.card}
        sessionId={sessionId}
        showCardLink={false}
      />
    </div>
  );
}