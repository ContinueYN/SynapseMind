"use client";

import { useState } from "react";

import { Surface } from "@/components/Surface";
import { getAgentTrace, runAgentTrace } from "@/src/lib/api/client";
import type { AgentStep, AgentTrace, VerificationMode } from "@/src/lib/api/types";

/**
 * 工具轨迹面板：让「系统做了什么」可见，但不把轨迹包装成诊断。
 *
 * v0.2 固定最多 3 步，只调用白名单里的只读工具；面板不展示思维链、不展示
 * 学生原文，也不把任何一步读成「答对了」。代码框只接收用户自己粘贴的最小
 * 复现；执行开关关闭时，后端会如实返回 skipped，面板不会把它说成通过。
 * reflection 只复述结构缺口与工具状态，不是卡点结论，也不排序选项。
 */

const TOOL_LABEL: Record<AgentStep["tool"], string> = {
  check_structure: "看结构",
  search_patterns: "查知识卡",
  search_sources: "查来源卡",
  compare_options: "列选项与代价",
  ask_clarifying: "提一个澄清问题",
  run_code: "运行复现",
  run_tests: "运行测试",
};

const STATUS_LABEL: Record<AgentStep["status"], string> = {
  ok: "完成",
  skipped: "未运行",
  failed: "失败",
};

interface AgentTracePanelProps {
  sessionId: string;
  verification: VerificationMode;
}

export function AgentTracePanel({
  sessionId,
  verification,
}: AgentTracePanelProps) {
  const [open, setOpen] = useState(false);
  const [trace, setTrace] = useState<AgentTrace | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [tests, setTests] = useState("");

  async function load() {
    setOpen(true);
    if (trace) return;
    setBusy(true);
    setError(null);
    try {
      setTrace(await getAgentTrace(sessionId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "读取工具轨迹失败。");
    } finally {
      setBusy(false);
    }
  }

  async function run() {
    const source = code.trim();
    if (!source || busy) return;
    setBusy(true);
    setError(null);
    try {
      setTrace(
        await runAgentTrace(sessionId, {
          code: source,
          tests: tests.trim() || undefined,
        }),
      );
      setOpen(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "运行复现失败。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Surface>
      <div className="sm-card">
        <div className="sm-card-head">
          <div className="sm-card-lab">
            <b>工具轨迹 · 只读</b>
            <span>最多 3 步 · 白名单</span>
          </div>
          <div className="sm-hint-tally" role="img" aria-label="工具轨迹只读">
            <b>≤3</b>
            <span>步数上限</span>
          </div>
        </div>

        <h2 className="sm-card-h">看看系统能查到什么，不能查到什么</h2>
        <p className="sm-card-sub">
          轨迹只记录工具名、输入/输出摘要和引用，不展示思维链，也不推进会话。
          任何一步都不等于“你的答案对了”。
        </p>

        <div className="sm-card-foot">
          <button
            className="sm-cta"
            disabled={busy}
            onClick={() => void (open ? setOpen(false) : load())}
            type="button"
          >
            {busy ? "正在整理" : open ? "收起工具轨迹" : "看工具轨迹（只读）"}
            <span aria-hidden="true" className="sm-ar">
              →
            </span>
          </button>
        </div>

        {open ? (
          <>
            {verification === "executable" ? (
              <div style={{ marginTop: 22 }}>
                <p className="sm-lab">可选：自己粘贴一段最小复现</p>
                <p className="sm-fine" style={{ marginTop: 8 }}>
                  只运行你显式提交的 Python；默认关闭，关闭时只记录「未运行」，
                  不会假装通过。执行器是受限本地进程，不是容器级安全沙箱。
                </p>
                <label className="sm-f" style={{ marginTop: 14 }}>
                  <span className="sm-f-label">Python 代码</span>
                  <textarea
                    disabled={busy}
                    maxLength={20000}
                    onChange={(event) => setCode(event.target.value)}
                    placeholder="粘贴能复现问题的最小代码，不要放隐私数据"
                    rows={5}
                    value={code}
                  />
                </label>
                <label className="sm-f">
                  <span className="sm-f-label">可选：unittest 测试文件</span>
                  <textarea
                    disabled={busy}
                    maxLength={20000}
                    onChange={(event) => setTests(event.target.value)}
                    placeholder="留空则只运行上面的代码"
                    rows={3}
                    value={tests}
                  />
                </label>
                <div className="sm-form-foot">
                  <button
                    className="sm-cta"
                    disabled={busy || !code.trim()}
                    onClick={() => void run()}
                    type="button"
                  >
                    {busy ? "正在运行" : "运行并记录轨迹"}
                    <span aria-hidden="true" className="sm-ar">
                      →
                    </span>
                  </button>
                  <span className="sm-fine">
                    最多 3 步；结果只说明这次运行，不构成诊断。
                  </span>
                </div>
              </div>
            ) : null}

            {error ? (
              <p className="sm-note" role="alert" style={{ marginTop: 16 }}>
                {error}
              </p>
            ) : null}

            {trace ? (
              <>
                <div style={{ marginTop: 22 }}>
                  <p className="sm-lab">我卡哪了（结构线索，不是诊断）</p>
                  <p className="sm-note sm-note-quiet" style={{ marginTop: 8 }}>
                    {trace.reflection.focus}
                  </p>
                  <p className="sm-lab" style={{ marginTop: 14 }}>
                    下一步做什么
                  </p>
                  <p className="sm-note sm-note-quiet" style={{ marginTop: 8 }}>
                    {trace.reflection.next}
                  </p>
                  <p className="sm-fine" style={{ marginTop: 10 }}>
                    {trace.reflection.boundary}
                  </p>
                </div>

                <p className="sm-lab" style={{ marginTop: 22 }}>
                  这次走过的步骤
                </p>
                <ol className="sm-steps">
                  {(trace.steps ?? []).map((step) => (
                    <li key={step.index}>
                      <b>{String(step.index).padStart(2, "0")}</b>
                      <span>
                        <strong>{TOOL_LABEL[step.tool]}</strong>
                        {" · "}
                        {STATUS_LABEL[step.status]}
                        <br />
                        {step.output_summary}
                        {(step.citations ?? []).map((citation) => (
                          <span key={citation.card_id} style={{ display: "block" }}>
                            <a
                              href={citation.source_url}
                              rel="noreferrer"
                              target="_blank"
                            >
                              {citation.source_title}
                            </a>
                            {` · ${citation.title} · ${citation.license}`}
                          </span>
                        ))}
                      </span>
                      <i>{step.duration_ms.toFixed(1)}ms</i>
                    </li>
                  ))}
                </ol>

                {(trace.suggestions ?? []).length > 0 ? (
                  <>
                    <p className="sm-lab" style={{ marginTop: 22 }}>
                      下一步可以自己核对
                    </p>
                    {(trace.suggestions ?? []).map((suggestion) => (
                      <p
                        className="sm-note sm-note-quiet"
                        key={`${suggestion.kind}-${suggestion.text}`}
                        style={{ marginTop: 8 }}
                      >
                        {suggestion.text}
                      </p>
                    ))}
                  </>
                ) : null}

                <p className="sm-fine" style={{ marginTop: 16 }}>
                  {trace.notice}（上限 {trace.limits.max_steps} 步，本轮用{" "}
                  {trace.limits.steps_used} 步）
                </p>
              </>
            ) : busy ? (
              <p className="sm-fine" style={{ marginTop: 16 }}>
                正在读取工具轨迹……
              </p>
            ) : null}
          </>
        ) : null}

        <p className="sm-fine" style={{ marginTop: 18 }}>
          没有工具调用就没有轨迹；没有执行就没有运行结果。不确定时，这里应该显示
          unknown / skipped，而不是替你补一个结论。
        </p>
      </div>
    </Surface>
  );
}