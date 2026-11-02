"use client";

import Link from "next/link";
import { useState } from "react";

import { Surface } from "@/components/ui/Surface";
import { requestCoach } from "@/src/lib/api/coach";
import { isUnauthorized } from "@/src/lib/api/http";
import type { CoachFocus, CoachPoint, CoachResult } from "@/src/lib/api/types";

/**
 * 「问 AI：我错在哪 / 怎么开始」——过程反馈，不是解法。
 *
 * 两个入口：`我错在哪`（where_wrong）和 `怎么开始`（how_to_start）。面板只展示
 * 后端给出的过程观察、一个下一步问题和 `not_claimed`；没有答案、分数、排名或
 * 能力评价。后端没有配置模型时返回 `rules`，这里如实写「规则版」；只有后端真的
 * 用了模型才写「模型版」。模型超时/坏 JSON 已在服务端回退规则版，面板按响应里的
 * `mode` 显示，不自己猜。
 *
 * 401 走既有的「请先登录」处理：浏览器没有 token 可加，只能去登录页拿 cookie。
 */

const KIND_LABEL: Record<CoachPoint["kind"], string> = {
  missing_evidence: "缺证据",
  missing_reasoning: "缺推理",
  missing_constraint: "缺约束",
  no_attempt: "还没有过程",
  next_step: "下一步",
  process_note: "过程提示",
};

const FOCUS_LABEL: Record<CoachFocus, string> = {
  where_wrong: "我错在哪",
  how_to_start: "怎么开始",
};

const MODE_LABEL: Record<CoachResult["mode"], string> = {
  rules: "规则版",
  llm: "模型版",
};

interface CoachPanelProps {
  sessionId: string;
  /** Where to return after login; only used for the 401 treatment. */
  next?: string;
}

export function CoachPanel({ sessionId, next = "/" }: CoachPanelProps) {
  const [result, setResult] = useState<CoachResult | null>(null);
  const [busyFocus, setBusyFocus] = useState<CoachFocus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [authRequired, setAuthRequired] = useState(false);

  async function ask(focus: CoachFocus) {
    if (busyFocus) return;
    setBusyFocus(focus);
    setError(null);
    setAuthRequired(false);
    try {
      setResult(await requestCoach(sessionId, focus));
    } catch (caught) {
      if (isUnauthorized(caught)) {
        setAuthRequired(true);
      } else {
        setError("这次没拿到过程反馈，请稍后再试。");
      }
    } finally {
      setBusyFocus(null);
    }
  }

  return (
    <Surface>
      <div className="sm-card">
        <div className="sm-card-head">
          <div className="sm-card-lab">
            <b>问 AI · 过程反馈</b>
            <span>不判对错 · 不给答案</span>
          </div>
          {result ? (
            <div className="sm-hint-tally" role="img" aria-label="反馈来源">
              <b>{MODE_LABEL[result.mode]}</b>
              <span>{result.mode === "llm" ? "模型措辞" : "固定规则"}</span>
            </div>
          ) : null}
        </div>

        <h2 className="sm-card-h">我错在哪，或者怎么开始</h2>
        <p className="sm-card-sub">
          它只根据题面和你自己写的文字给过程提示；不读答案库，也不评价你。
        </p>

        <div className="sm-card-foot" style={{ marginTop: 16 }}>
          <button
            className="sm-link"
            disabled={busyFocus !== null}
            onClick={() => void ask("where_wrong")}
            type="button"
          >
            {busyFocus === "where_wrong" ? "正在整理……" : "我错在哪"}
          </button>
          <button
            className="sm-link sm-link-quiet"
            disabled={busyFocus !== null}
            onClick={() => void ask("how_to_start")}
            type="button"
          >
            {busyFocus === "how_to_start" ? "正在整理……" : "怎么开始"}
          </button>
          {busyFocus ? (
            <span className="sm-fine" role="status">
              正在整理过程反馈……
            </span>
          ) : null}
        </div>

        {authRequired ? (
          <p className="sm-note" role="status" style={{ marginTop: 16 }}>
            请先登录：会话接口需要 HttpOnly cookie，这里没有可写的 token。
            <Link className="sm-link" href={`/login?next=${encodeURIComponent(next)}`}>
              去登录
            </Link>
          </p>
        ) : null}

        {error ? (
          <p className="sm-alert" role="alert" style={{ marginTop: 16 }}>
            {error}
          </p>
        ) : null}

        {result ? (
          <>
            <div style={{ marginTop: 20 }}>
              <p className="sm-kicker">
                {MODE_LABEL[result.mode]} · {FOCUS_LABEL[result.focus]}
              </p>
              <p className="sm-note" role="status">
                {result.headline}
              </p>
            </div>

            <p className="sm-lab" style={{ marginTop: 20 }}>
              过程观察
            </p>
            <ul aria-label="过程反馈" className="sm-steps">
              {result.points.map((point, index) => (
                <li data-status="covered" key={`${point.kind}-${index}`}>
                  <b>{String(index + 1).padStart(2, "0")}</b>
                  <span>{point.text}</span>
                  <i>{KIND_LABEL[point.kind]}</i>
                </li>
              ))}
            </ul>

            <p className="sm-note" style={{ marginTop: 16 }}>
              <b>下一个问题：</b>
              {result.next_question}
            </p>

            <p className="sm-lab" style={{ marginTop: 18 }}>
              这次没有判断
            </p>
            <ul className="sm-fine">
              {result.not_claimed.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>

            <p className="sm-fine" style={{ marginTop: 14 }}>
              {result.disclaimer}
            </p>
          </>
        ) : null}
      </div>
    </Surface>
  );
}