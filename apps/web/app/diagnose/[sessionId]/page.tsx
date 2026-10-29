"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { DiagnosisCardView } from "@/components/DiagnosisCardView";
import { GlassCard } from "@/components/GlassCard";
import { LiquidVessel } from "@/components/LiquidVessel";
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

  async function send(answer: string, optionId: string) {
    setBusy(true);
    setError(null);
    try {
      setSession(await submitTurn(sessionId, { answer, option_id: optionId }));
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
      <section className="sm-state">
        <p className="sm-kicker">会话没打开</p>
        <h1 className="sm-h1">{error}</h1>
        <p className="sm-p">诊断服务可能在 8000 端口没起来。</p>
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
        <p className="sm-kicker">正在恢复会话</p>
        <h1 className="sm-h1">先看一下你刚才写到哪。</h1>
      </section>
    );
  }

  const located = Boolean(session.diagnosis);

  return (
    <div>
      <div className="sm-screenbar">
        <span>{located ? "屏 03" : "屏 02"}</span>
        <b>{located ? "定位 · 处置" : "拆题 · 追问"}</b>
        <i>{session.problem_title}</i>
      </div>

      <div className="sm-work">
        <aside className="sm-work-side">
          <LiquidVessel maxTurns={session.max_turns} turn={session.turn} />
          <div>
            <p className="sm-lab">诊断进度</p>
            <p className="sm-turn">
              {session.turn}
              <small>/ {session.max_turns} 轮</small>
            </p>
            <div style={{ marginTop: 14 }}>
              <ProgressRail state={session.state} />
            </div>
          </div>
        </aside>

        <div className="sm-work-main">
          <Transcript items={session.history ?? []} />

          {session.diagnosis ? (
            <DiagnosisCardView card={session.diagnosis.card} sessionId={sessionId} />
          ) : session.prompt ? (
            <GlassCard>
              <ProbeCard
                busy={busy}
                onExit={leave}
                onSelect={send}
                onUnknown={() => send("不会", "unknown")}
                probe={session.prompt}
              />
            </GlassCard>
          ) : (
            <GlassCard>
              <p className="sm-kicker">本轮结束</p>
              <h2 className="sm-h2">{session.notice ?? "先停在这里。"}</h2>
              <p className="sm-p">
                没有足够证据时，系统不硬判卡点。回交题页补一步更具体的过程，会让定位更准。
              </p>
              <div className="sm-card-acts">
                <Link className="sm-act" href="/">
                  重新交一道题
                  <span aria-hidden="true" className="sm-ar">
                    →
                  </span>
                </Link>
              </div>
            </GlassCard>
          )}

          {error && session ? (
            <p className="sm-alert" role="alert" style={{ marginTop: 16 }}>
              {error}
            </p>
          ) : null}
        </div>
      </div>

      <p className="sm-fine">
        这一轮的原则：一次只问一个可回答的问题；不重复问；前 3 轮不给最终答案。
      </p>
    </div>
  );
}