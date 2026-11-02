"use client";

import { useState, type FormEvent } from "react";

import { runReview } from "@/src/lib/api/client";
import type {
  GenericReview,
  GenericReviewEvidence,
  GenericReviewFinding,
  GenericReviewOption,
  VerificationMode,
} from "@/src/lib/api/types";

/**
 * 通用产物的展示壳：结构复盘 / 决策框 / 代码复现卡。
 *
 * 它不是卡点卡，也不给分：结构复盘的每条 finding 都是「看到 / 没看到」的覆盖
 * 说明；决策框只按学生写到的顺序列出选项、代价、风险与可逆实验，不排序、不推荐，
 * 没有 score/rank/recommended 这类字段或 DOM。
 *
 * v0.1（T4）起多了 execution 分支：只有 `verification="executable"` 的入口才显示
 * 代码/测试输入，输入框默认空、绝不预填题面或作答；只有用户显式点击提交才会请求
 * `POST /sessions/{id}/review/run`。结果按 pass / fail / timeout / rejected /
 * skipped 分别措辞——skipped 只表示没有运行，不能渲染成通过；pass 也只表示退出码
 * 0 或提交的测试通过。代码复现卡本身不是诊断，Agent 轨迹仍是页面上的另一条旁路。
 *
 * 知识卡证据（T5）是 top-level 来源：只显示检索返回的卡片 id 与标题，不显示相似度
 * 分数、不排序、不推荐，也不把它写成 finding 或评分。
 */

const SEVERITY_LABEL: Record<GenericReviewFinding["severity"], string> = {
  blocking: "主要缺口",
  notable: "次要缺口",
};

const EVIDENCE_SOURCE_LABEL: Record<GenericReviewEvidence["source"], string> = {
  student: "学生原话",
  graph: "结构图",
  execution: "执行记录",
  knowledge: "知识卡",
};

type ExecutionRecord = NonNullable<GenericReview["execution"]>;

const EXECUTION_STATUS_LABEL: Record<ExecutionRecord["status"], string> = {
  pass: "这次运行通过（pass）",
  fail: "这次运行没有通过（fail）",
  timeout: "运行超时（timeout）",
  rejected: "执行被拒绝（rejected），代码没有运行",
  skipped: "没有运行（skipped），执行开关关闭",
};

const EXECUTION_STATUS_NOTE: Record<ExecutionRecord["status"], string> = {
  pass: "pass 只表示退出码 0 或提交的测试通过，不表示代码正确或完整。",
  fail: "fail 只表示这次运行没有通过；首个失败见下面，不表示已经找到根因。",
  timeout: "timeout 只表示进程没有在时限内结束，不表示代码正确或错误。",
  rejected: "rejected 表示静态闸门拒绝了代码，代码根本没有运行。",
  skipped: "skipped 只表示这次没有运行；执行开关默认关闭，不返回 pass。",
};

function evidenceSummary(items: GenericReviewEvidence[]): string {
  const counts = new Map<GenericReviewEvidence["source"], number>();
  for (const item of items) {
    counts.set(item.source, (counts.get(item.source) ?? 0) + 1);
  }
  return [...counts]
    .map(([source, count]) => `${EVIDENCE_SOURCE_LABEL[source]} ${count} 条`)
    .join("、");
}

function FindingList({
  findings,
  label = "看到的与还缺的",
}: {
  findings: GenericReviewFinding[];
  label?: string;
}) {
  if (findings.length === 0) return null;
  return (
    <ul aria-label={label} className="sm-steps">
      {findings.map((finding) => (
        <li key={finding.id}>
          <b>{finding.label}</b>
          <span>{finding.summary}</span>
          <i>{SEVERITY_LABEL[finding.severity]}</i>
        </li>
      ))}
    </ul>
  );
}

function OptionList({ options }: { options: GenericReviewOption[] }) {
  return (
    <ol aria-label="选项（按你写到的顺序）" className="sm-steps">
      {options.map((option, index) => (
        <li key={`${index}-${option.label}`}>
          <b>{String(index + 1).padStart(2, "0")}</b>
          <span>
            <strong>{option.label}</strong>
            {"　"}代价：{option.costs.length > 0 ? option.costs.join("；") : "还没写"}
            {"　"}风险：{option.risks.length > 0 ? option.risks.join("；") : "还没写"}
            {"　"}可逆实验：{option.reversible_test || "还没写"}
          </span>
          <i>选项</i>
        </li>
      ))}
    </ol>
  );
}

interface GenericReviewViewProps {
  /** `null` means "no review yet": only an executable session renders the form. */
  review: GenericReview | null;
  /** The intake's verification mode; the run card is exclusive to `executable`. */
  verification?: VerificationMode;
  /** Present only for an intake session; required before a run can be submitted. */
  sessionId?: string;
}

/**
 * The explicit-submission card. It owns the request so the surrounding intake
 * does not have to store a derived artifact: a run result is not session state.
 */
function ExecutionReviewCard({
  review,
  sessionId,
  canRun,
}: {
  review: GenericReview | null;
  sessionId?: string;
  canRun: boolean;
}) {
  const [code, setCode] = useState("");
  const [tests, setTests] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // A run result is not session state: prefer the latest explicit submission,
  // then fall back to the review the caller passed in.
  const [submitted, setSubmitted] = useState<GenericReview | null>(null);
  const shown = submitted ?? review;
  const execution = shown?.execution ?? null;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const source = code.trim();
    // The server is the authority (409 for non-executable, skipped when off);
    // the button is only disabled to avoid an obviously empty request.
    if (!canRun || !sessionId || !source || busy) return;
    setBusy(true);
    setError(null);
    try {
      setSubmitted(
        await runReview(sessionId, {
          code: source,
          tests: tests.trim() || undefined,
        }),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "运行复现失败。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="代码复现卡">
      <p className="sm-lab" style={{ marginTop: 26 }}>
        代码复现卡 · 只跑你显式提交的代码
      </p>
      <p className="sm-note" style={{ marginTop: 8 }}>
        把最小复现代码粘进来（可选一个 unittest 测试文件）。系统只运行这一次提交，
        不会从题面、作答或轨迹里替你抽代码；执行默认关闭。
      </p>

      {execution ? (
        <>
          <p className="sm-note" style={{ marginTop: 16 }}>
            <b>{EXECUTION_STATUS_LABEL[execution.status]}</b>
            {"　"}
            {execution.tests_submitted ? "本次提交了测试" : "本次没有提交测试"}
          </p>
          <p className="sm-fine" style={{ marginTop: 6 }}>
            {EXECUTION_STATUS_NOTE[execution.status]}
          </p>
          <p className="sm-note" style={{ marginTop: 10 }}>
            {shown?.headline}
          </p>

          {execution.first_failure ? (
            <>
              <p className="sm-lab" style={{ marginTop: 18 }}>
                首个失败
              </p>
              <p className="sm-note sm-note-quiet" style={{ marginTop: 6 }}>
                {execution.first_failure}
              </p>
            </>
          ) : null}

          {execution.stdout_excerpt ? (
            <>
              <p className="sm-lab" style={{ marginTop: 18 }}>
                输出摘要
              </p>
              <p className="sm-note sm-note-quiet" style={{ marginTop: 6 }}>
                {execution.stdout_excerpt}
              </p>
            </>
          ) : null}

          {shown && (shown.findings ?? []).length > 0 ? (
            <>
              <p className="sm-lab" style={{ marginTop: 18 }}>
                这次运行记录
              </p>
              <FindingList findings={shown.findings ?? []} label="运行记录" />
            </>
          ) : null}

          {shown && (shown.evidence ?? []).length > 0 ? (
            <p className="sm-fine" style={{ marginTop: 10 }}>
              证据 {(shown.evidence ?? []).length} 条：
              {evidenceSummary(shown.evidence ?? [])}。
            </p>
          ) : null}

          {shown && (shown.not_checked ?? []).length > 0 ? (
            <>
              <p className="sm-lab" style={{ marginTop: 20 }}>
                这次没有检查
              </p>
              {(shown.not_checked ?? []).map((item) => (
                <p className="sm-fine" key={item} style={{ marginTop: 6 }}>
                  {item}
                </p>
              ))}
            </>
          ) : null}

          {shown ? (
            <>
              <p className="sm-note" style={{ marginTop: 14 }}>
                {shown.next_step}
              </p>
              <p className="sm-note sm-note-quiet" style={{ marginTop: 10 }}>
                {shown.disclaimer}
              </p>
            </>
          ) : null}
        </>
      ) : (
        <p className="sm-fine" style={{ marginTop: 12 }}>
          还没有运行：提交后这里才会出现结果。未运行不会被写成通过。
        </p>
      )}

      {canRun ? (
        <form className="sm-form" onSubmit={submit} style={{ marginTop: 18 }}>
          <label className="sm-f">
            <span className="sm-f-label">Python 代码</span>
            <textarea
              disabled={busy}
              maxLength={20000}
              onChange={(event) => setCode(event.target.value)}
              placeholder="只粘贴你要复现的代码；留空不会运行"
              rows={8}
              value={code}
            />
          </label>
          <label className="sm-f">
            <span className="sm-f-label">可选：unittest 测试文件</span>
            <textarea
              disabled={busy}
              maxLength={20000}
              onChange={(event) => setTests(event.target.value)}
              placeholder="留空表示这次不提交测试"
              rows={4}
              value={tests}
            />
          </label>
          <div className="sm-form-foot">
            <button
              className="sm-cta"
              disabled={busy || !code.trim()}
              type="submit"
            >
              {busy ? "正在运行……" : "运行并生成复现卡"}
            </button>
            <span className="sm-fine">
              {execution
                ? "改完可以再提交一次；每次只替换上面的结果。"
                : "只运行你粘进来的这一次；不读答案、不写会话。"}
            </span>
          </div>
        </form>
      ) : null}

      {error ? (
        <p className="sm-alert" role="alert" style={{ marginTop: 14 }}>
          {error}
        </p>
      ) : null}

      <p className="sm-fine" style={{ marginTop: 16 }}>
        这里是显式提交的旁路产物：只记录这一次运行，不定位卡点，也不替你判断代码
        是否正确。工具轨迹在页面下方单独展示。
      </p>
    </section>
  );
}

export function GenericReviewView({
  review,
  verification,
  sessionId,
}: GenericReviewViewProps) {
  // The run card exists only for an executable promise. A structure/decision
  // review never gets a code box, even if a session id happens to be passed.
  const canRun = verification === "executable" && Boolean(sessionId);

  if (review === null) {
    return canRun && sessionId ? (
      <ExecutionReviewCard review={null} sessionId={sessionId} canRun />
    ) : null;
  }

  if (review.kind === "execution") {
    return (
      <ExecutionReviewCard
        review={review}
        sessionId={sessionId}
        canRun={canRun}
      />
    );
  }

  const decision = review.kind === "decision";
  const findings = review.findings ?? [];
  const evidence = review.evidence ?? [];
  const knowledgeEvidence = evidence.filter((item) => item.source === "knowledge");
  const notChecked = review.not_checked ?? [];
  const options = review.options ?? [];

  return (
    <section aria-label={decision ? "决策框" : "结构复盘"}>
      <p className="sm-lab" style={{ marginTop: 26 }}>
        {decision ? "决策框 · 不排序、不推荐" : "结构复盘 · 只看写到没写到"}
      </p>
      <p className="sm-note" style={{ marginTop: 8 }}>
        {review.headline}
      </p>

      {decision ? (
        <>
          <OptionList options={options} />
          {review.tradeoff_question ? (
            <p className="sm-note sm-note-quiet" style={{ marginTop: 16 }}>
              取舍问题：{review.tradeoff_question}
            </p>
          ) : null}
        </>
      ) : null}

      <p className="sm-lab" style={{ marginTop: 22 }}>
        还缺的结构
      </p>
      <FindingList findings={findings} />
      {findings.length === 0 ? (
        <p className="sm-fine" style={{ marginTop: 8 }}>
          这次没有可逐条列出的结构项；见下面的“这次没有检查”。
        </p>
      ) : null}

      {evidence.length > 0 ? (
        <p className="sm-fine" style={{ marginTop: 12 }}>
          证据 {evidence.length} 条：{evidenceSummary(evidence)}。
        </p>
      ) : null}

      {knowledgeEvidence.length > 0 ? (
        <>
          <p className="sm-lab" style={{ marginTop: 18 }}>
            可追来源
          </p>
          <ul aria-label="知识卡来源（id 与标题）" className="sm-steps">
            {knowledgeEvidence.map((item) => (
              <li key={item.id}>
                <b>{item.ref}</b>
                <span>{item.excerpt ?? "（标题未提供）"}</span>
                <i>知识卡</i>
              </li>
            ))}
          </ul>
          <p className="sm-fine" style={{ marginTop: 6 }}>
            只列检索到的卡片 id 与标题；不显示相似度分数，也不把卡片当作评分。
          </p>
        </>
      ) : null}

      {notChecked.length > 0 ? (
        <>
          <p className="sm-lab" style={{ marginTop: 22 }}>
            这次没有检查
          </p>
          {notChecked.map((item) => (
            <p className="sm-fine" key={item} style={{ marginTop: 6 }}>
              {item}
            </p>
          ))}
        </>
      ) : null}

      <p className="sm-note" style={{ marginTop: 16 }}>
        {review.next_step}
      </p>
      <p className="sm-note sm-note-quiet" style={{ marginTop: 12 }}>
        {review.disclaimer}
      </p>
    </section>
  );
}