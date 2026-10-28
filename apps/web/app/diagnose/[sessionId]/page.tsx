"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { DiagnosisCardView } from "@/components/DiagnosisCardView";
import { ProbeCard } from "@/components/ProbeCard";
import { ProgressRail } from "@/components/ProgressRail";
import { Transcript } from "@/components/Transcript";
import { exitSession, getSession, submitTurn } from "@/src/lib/api/client";
import type { SessionResponse } from "@/src/lib/api/types";

export default function DiagnosePage() {
  const params = useParams<{ sessionId: string }>();
  const sessionId = params.sessionId;
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getSession(sessionId)
      .then((value) => {
        if (!cancelled) setSession(value);
      })
      .catch((caught) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "加载会话失败。");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  async function answer(optionId: string, optionText: string) {
    setBusy(true);
    setError(null);
    try {
      setSession(
        await submitTurn(sessionId, { answer: optionText, option_id: optionId }),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "提交失败，请重试。");
    } finally {
      setBusy(false);
    }
  }

  async function unknown() {
    setBusy(true);
    setError(null);
    try {
      setSession(
        await submitTurn(sessionId, { answer: "不会", option_id: "unknown" }),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "提交失败，请重试。");
    } finally {
      setBusy(false);
    }
  }

  async function leave() {
    setBusy(true);
    setError(null);
    try {
      setSession(await exitSession(sessionId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "退出失败，请重试。");
    } finally {
      setBusy(false);
    }
  }

  if (error && !session) {
    return (
      <section className="state-panel">
        <h1>会话没打开</h1>
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
        <p className="eyebrow">正在恢复会话</p>
        <h1>先看一下你刚才写到哪。</h1>
      </section>
    );
  }

  return (
    <div className="diagnose-layout">
      <div className="diagnose-main">
        <div className="session-meta">
          <span>{session.problem_title}</span>
          <span className="muted">{session.session_id}</span>
        </div>
        <ProgressRail
          turn={session.turn}
          maxTurns={session.max_turns}
          confidence={session.progress.confidence}
          topHypothesis={session.progress.top_hypothesis}
        />

        {session.diagnosis ? (
          <DiagnosisCardView card={session.diagnosis.card} sessionId={sessionId} />
        ) : session.prompt ? (
          <ProbeCard
            busy={busy}
            onExit={leave}
            onSelect={answer}
            onUnknown={unknown}
            probe={session.prompt}
          />
        ) : (
          <section className="state-panel">
            <p className="eyebrow">本轮结束</p>
            <h1>{session.notice ?? "先停在这里。"}</h1>
            <p>
              没有足够证据时，系统不硬判卡点。你可以回到交题页，补一步更具体的过程。
            </p>
            <Link className="primary-link" href="/">
              重新交一道题
            </Link>
          </section>
        )}
        {error && session ? <p className="inline-error">{error}</p> : null}
      </div>
      <aside className="diagnose-aside">
        <Transcript items={session.history ?? []} />
        <section className="principle-card">
          <p className="eyebrow">这一轮的原则</p>
          <p>一次只问一个可回答的问题；不重复问；前 3 轮不给最终答案。</p>
        </section>
      </aside>
    </div>
  );
}