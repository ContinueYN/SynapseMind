"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { DiagnosisCardView } from "@/components/DiagnosisCardView";
import { KnowledgePanel } from "@/components/KnowledgePanel";
import { Plane } from "@/components/Plane";
import { ProblemBrief } from "@/components/ProblemBrief";
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
        <Plane>
          <p className="sm-kicker">卡点卡没打开</p>
          <h1 className="sm-h1">{error}</h1>
          <p style={{ marginTop: 26 }}>
            <Link className="sm-cta" href="/">
              回到交题页
              <span aria-hidden="true" className="sm-ar">
                →
              </span>
            </Link>
          </p>
        </Plane>
      </section>
    );
  }

  if (!session) {
    return (
      <section className="sm-state">
        <Plane>
          <p className="sm-kicker">正在读取</p>
          <h1 className="sm-h1">把证据整理成一张卡。</h1>
          <p className="sm-p" style={{ marginTop: 24 }}>
            <span className="sm-tl-shim" />
          </p>
        </Plane>
      </section>
    );
  }

  if (!session.diagnosis) {
    return (
      <section className="sm-state">
        <Plane>
          <p className="sm-kicker">还没有卡点卡</p>
          <h1 className="sm-h1">这次还没收敛到一处。</h1>
          <p className="sm-p">
            {session.notice ?? "追问还没收敛；先回到对话继续，或补一步过程。"}
          </p>
          <p style={{ marginTop: 26 }}>
            <Link className="sm-cta" href={`/diagnose/${sessionId}`}>
              回到对话
              <span aria-hidden="true" className="sm-ar">
                →
              </span>
            </Link>
          </p>
        </Plane>
      </section>
    );
  }

  return (
    <div className="sm-dossier">
      <div className="sm-dossier-bar">
        <div>
          <p className="sm-kicker" style={{ marginBottom: 2 }}>
            卡点卡
          </p>
          <p className="sm-stage-title">{session.problem_title}</p>
        </div>
        <div className="sm-dossier-tools">
          <Link className="sm-link sm-link-quiet" href={`/diagnose/${sessionId}`}>
            ← 回到对话
          </Link>
          <button className="sm-link" onClick={() => window.print()} type="button">
            打印 / 存为 PDF
          </button>
        </div>
      </div>

      <ProblemBrief defaultOpen={false} text={session.problem_text} />

      <DiagnosisCardView
        card={session.diagnosis.card}
        sessionId={sessionId}
        showCardLink={false}
      />
      <KnowledgePanel
        query={session.diagnosis.card.label}
        subject={session.subject}
      />
    </div>
  );
}