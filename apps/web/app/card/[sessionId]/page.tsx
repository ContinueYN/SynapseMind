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
      <section className="sm-state">
        <p className="sm-kicker">卡点卡没打开</p>
        <h1 className="sm-h1">{error}</h1>
        <div className="sm-card-acts">
          <Link className="sm-act" href="/">
            回到交题页
            <span aria-hidden="true" className="sm-ar">
              →
            </span>
          </Link>
        </div>
      </section>
    );
  }

  if (!session) {
    return (
      <section className="sm-state">
        <p className="sm-kicker">正在读取</p>
        <h1 className="sm-h1">把证据整理成一张卡。</h1>
      </section>
    );
  }

  if (!session.diagnosis) {
    return (
      <section className="sm-state">
        <p className="sm-kicker">还没有卡点卡</p>
        <h1 className="sm-h1">这次还没收敛到一处。</h1>
        <p className="sm-p">
          {session.notice ?? "追问还没收敛；先回到对话继续，或补一步过程。"}
        </p>
        <div className="sm-card-acts">
          <Link className="sm-act" href={`/diagnose/${sessionId}`}>
            回到对话
            <span aria-hidden="true" className="sm-ar">
              →
            </span>
          </Link>
        </div>
      </section>
    );
  }

  return (
    <div>
      <div className="sm-screenbar">
        <span>屏 03</span>
        <b>卡点卡</b>
        <i>{session.problem_title}</i>
      </div>

      <div style={{ marginTop: 18 }}>
        <Link className="sm-bail" href={`/diagnose/${sessionId}`}>
          ← 回到对话
        </Link>
      </div>

      <div className="sm-band">
        <DiagnosisCardView
          card={session.diagnosis.card}
          sessionId={sessionId}
          showCardLink={false}
        />
      </div>
    </div>
  );
}