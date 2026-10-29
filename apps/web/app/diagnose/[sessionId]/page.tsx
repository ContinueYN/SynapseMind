"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Dendrite, type DendriteStop } from "@/components/Dendrite";
import { DiagnosisCardView } from "@/components/DiagnosisCardView";
import { Plane } from "@/components/Plane";
import { ProblemBrief } from "@/components/ProblemBrief";
import { Surface } from "@/components/Surface";
import { ProbeCard } from "@/components/ProbeCard";
import { Thread } from "@/components/Thread";
import { ApiError, exitSession, getSession, submitTurn } from "@/src/lib/api/client";
import type { SessionResponse } from "@/src/lib/api/types";
import { adoptSession } from "@/src/lib/session-handoff";

const PHASE: Record<string, string> = {
  INGEST: "收题",
  PARSE: "拆题",
  NEED_INPUT: "等你补一句",
  ALIGN: "对齐",
  PROBE: "追问",
  DIAGNOSE: "定位",
  INTERVENE: "定位",
  VERIFY: "定位",
  STOP: "停下",
  CLOSED: "已结束",
};

function shorten(text: string, limit = 11) {
  const clean = text.replace(/\s+/g, " ").trim();
  return clean.length > limit ? `${clean.slice(0, limit)}…` : clean;
}

export default function DiagnosePage() {
  const params = useParams<{ sessionId: string }>();
  const sessionId = params.sessionId;

  const [session, setSession] = useState<SessionResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<{ answer: string; unknown: boolean } | null>(
    null,
  );
  /* 指针停在哪一轮问答上，左轨对应的节点跟着亮 */
  const [hotTurn, setHotTurn] = useState<number | null>(null);

  const probeRef = useRef<HTMLDivElement>(null);
  const lastTurn = useRef<number | null>(null);

  useEffect(() => {
    const handed = adoptSession(sessionId);
    if (handed) {
      setSession(handed);
      return;
    }
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

  /* 换了一问之后，只有在它被挤出视口时才滚一下——不做整页跳转 */
  useEffect(() => {
    if (!session) return;
    if (lastTurn.current === null) {
      lastTurn.current = session.turn;
      return;
    }
    if (session.turn === lastTurn.current) return;
    lastTurn.current = session.turn;
    probeRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [session]);

  async function send(optionId: string, answerText: string) {
    if (busy) return;
    setPending({ answer: answerText, unknown: optionId === "unknown" });
    setBusy(true);
    setError(null);
    try {
      setSession(
        await submitTurn(sessionId, {
          answer: answerText,
          option_id: optionId || undefined,
        }),
      );
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 422) {
        setError("这一问要从选项里选一个；也可以点「我还是不懂」，换成更低的台阶。");
      } else {
        setError(caught instanceof Error ? caught.message : "提交失败，请重试。");
      }
    } finally {
      setBusy(false);
      setPending(null);
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
        <Plane>
          <p className="sm-kicker">会话没打开</p>
          <h1 className="sm-h1">{error}</h1>
          <p className="sm-p">诊断服务可能在 8000 端口没起来；也可以先回到交题页。</p>
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
          <p className="sm-kicker">正在恢复会话</p>
          <h1 className="sm-h1">先看一下你刚才写到哪。</h1>
          <p className="sm-p" style={{ marginTop: 24 }}>
            <span className="sm-tl-shim" />
          </p>
        </Plane>
      </section>
    );
  }

  const located = Boolean(session.diagnosis);
  const confidence = Math.round((session.progress?.confidence ?? 0) * 100);
  const history = session.history ?? [];

  const stops: DendriteStop[] = history.map((item) => ({
    id: `t${item.turn}`,
    label: `第 ${item.turn} 问`,
    detail: item.is_unknown ? "不知道，退一级" : shorten(item.answer),
    state: "done",
    hint: item.action === "hint",
    hot: hotTurn === item.turn,
  }));

  if (session.diagnosis) {
    stops.push({
      id: "stuck",
      label: "卡点",
      detail: session.diagnosis.card.label,
      state: "stuck",
    });
  } else if (session.prompt) {
    stops.push({
      id: "now",
      label: `第 ${session.turn + 1} 问`,
      detail: "正在问",
      state: "active",
      hint: session.prompt.action === "hint",
    });
  }

  return (
    <div>
      <div className="sm-session">
        <aside className="sm-rail sm-plane">
          <div>
            <p className="sm-lab">诊断进度</p>
            <p className="sm-rail-turn">
              {session.turn}
              <small>/ {session.max_turns} 轮</small>
            </p>
            <p className="sm-rail-phase">{PHASE[session.state] ?? session.state}</p>
          </div>

          <Dendrite step={46} stops={stops} />

          <div className="sm-signal">
            <div className="sm-signal-top">
              <span className="sm-signal-lab">系统把握</span>
              <span className="sm-signal-v">{confidence}%</span>
            </div>
            <div
              aria-label={`系统把握 ${confidence}%`}
              aria-valuemax={100}
              aria-valuemin={0}
              aria-valuenow={confidence}
              className="sm-bar"
              role="progressbar"
            >
              <i style={{ width: `${Math.max(4, confidence)}%` }} />
            </div>
            <p className="sm-signal-note">
              {located ? "已经收敛到一处，证据在右边。" : "把握到 80% 才出卡。"}
            </p>
          </div>
        </aside>

        <section className="sm-stage sm-plane">
          <div className="sm-stage-head">
            <p className="sm-stage-title">{session.problem_title}</p>
            <span className="sm-stage-tag">{located ? "定位" : "追问"}</span>
          </div>

          <ProblemBrief text={session.problem_text} />

          <Thread hotTurn={hotTurn} items={history} onHoverTurn={setHotTurn} pending={pending} />

          <div ref={probeRef}>
            {session.diagnosis ? (
              <DiagnosisCardView card={session.diagnosis.card} sessionId={sessionId} />
            ) : session.prompt ? (
              <ProbeCard
                busy={busy}
                onExit={leave}
                onSelect={send}
                onUnknown={() => send("unknown", "不会")}
                probe={session.prompt}
                turn={session.turn + 1}
              />
            ) : (
              <Surface>
                <p className="sm-kicker">本轮结束</p>
                <h2 className="sm-h2">{session.notice ?? "先停在这里。"}</h2>
                <p className="sm-p">
                  没有足够证据时，系统不硬判卡点。回交题页补一步更具体的过程，会让定位更准。
                </p>
                <p style={{ marginTop: 24 }}>
                  <Link className="sm-cta" href="/">
                    重新交一道题
                    <span aria-hidden="true" className="sm-ar">
                      →
                    </span>
                  </Link>
                </p>
              </Surface>
            )}
          </div>

          {error ? (
            <p className="sm-alert" role="alert" style={{ marginTop: 18 }}>
              {error}
            </p>
          ) : null}

          <p className="sm-fine">
            一次只问一个；问过的不会再问；前三轮不给答案。
          </p>
        </section>
      </div>
    </div>
  );
}