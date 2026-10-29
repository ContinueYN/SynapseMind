"use client";

import { FormEvent, MouseEvent, useRef, useState } from "react";

import type { CreateSessionInput } from "@/src/lib/api/types";

interface ProblemFormProps {
  busy: boolean;
  error: string | null;
  onSubmit: (input: CreateSessionInput) => Promise<void>;
}

type SelfReport = NonNullable<CreateSessionInput["attempt"]["self_report"]>;

const SAMPLE_PROBLEM =
  "已知函数 f(x)=ln x - a x，a∈R。若 f(x)≤0 对任意 x>0 恒成立，求 a 的取值范围。";
const SAMPLE_WORK =
  "定义域 x>0。f'(x)=1/x-a，令 f'(x)=0 得 x=1/a。a>0 时，最大值为 f(1/a)=-ln a-1≤0，所以 a≥1/e。";

const SELF_REPORTS: { value: SelfReport; label: string }[] = [
  { value: "wrong", label: "做错了" },
  { value: "unsure", label: "不确定" },
  { value: "correct_but_guessed", label: "对了但有点蒙" },
  { value: "no_idea", label: "完全不会" },
];

export function ProblemForm({ busy, error, onSubmit }: ProblemFormProps) {
  const [problemText, setProblemText] = useState("");
  const [answer, setAnswer] = useState("");
  const [work, setWork] = useState("");
  const [stuckAt, setStuckAt] = useState("");
  const [selfReport, setSelfReport] = useState<SelfReport>("unsure");
  const [localError, setLocalError] = useState<string | null>(null);
  const submitRef = useRef<HTMLButtonElement>(null);

  function fillSample() {
    setProblemText(SAMPLE_PROBLEM);
    setWork(SAMPLE_WORK);
    setAnswer("a≥1/e");
    setStuckAt("令导数为 0 那一步，不确定要不要先管 a 是正是负");
    setSelfReport("correct_but_guessed");
    setLocalError(null);
  }

  function ripple(event: MouseEvent<HTMLButtonElement>) {
    const button = submitRef.current;
    if (!button) return;
    const rect = button.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height) * 2.4;
    const span = document.createElement("span");
    span.className = "sm-ripple";
    span.style.width = `${size}px`;
    span.style.height = `${size}px`;
    span.style.left = `${event.clientX - rect.left}px`;
    span.style.top = `${event.clientY - rect.top}px`;
    button.appendChild(span);
    window.setTimeout(() => span.remove(), 720);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLocalError(null);

    if (!problemText.trim()) {
      setLocalError("先把题目粘进来。");
      return;
    }
    if (!answer.trim()) {
      setLocalError("填一个答案；完全不会就写“不会”。");
      return;
    }

    await onSubmit({
      problem: { text: problemText.trim() },
      attempt: {
        answer: answer.trim(),
        work: work.trim(),
        stuck_at: stuckAt.trim() || undefined,
        self_report: selfReport,
      },
      mode: "learning",
    });
  }

  return (
    <form className="sm-fields" onSubmit={handleSubmit}>
      <div className="sm-field">
        <label className="sm-field-k" htmlFor="field-problem">
          题目<em>必填</em>
        </label>
        <label className="sm-inp">
          <textarea
            id="field-problem"
            onChange={(event) => setProblemText(event.target.value)}
            placeholder="粘贴题目；只有照片的话，把题干敲成一行也行"
            rows={3}
            value={problemText}
          />
        </label>
      </div>

      <div className="sm-field">
        <label className="sm-field-k" htmlFor="field-answer">
          你的答案<em>必填</em>
        </label>
        <label className="sm-inp">
          <input
            id="field-answer"
            onChange={(event) => setAnswer(event.target.value)}
            placeholder="例如 a≥1/e；完全不会就写“不会”"
            type="text"
            value={answer}
          />
        </label>
      </div>

      <div className="sm-field">
        <label className="sm-field-k" htmlFor="field-work">
          你的过程
        </label>
        <label className="sm-inp">
          <textarea
            id="field-work"
            onChange={(event) => setWork(event.target.value)}
            placeholder="写多少都行；没有过程就留空"
            rows={4}
            value={work}
          />
        </label>
      </div>

      <div className="sm-field">
        <label className="sm-field-k" htmlFor="field-stuck">
          卡在哪
        </label>
        <label className="sm-inp">
          <input
            id="field-stuck"
            onChange={(event) => setStuckAt(event.target.value)}
            placeholder="一句话就行，例如：写到求导就不确定要不要分类"
            type="text"
            value={stuckAt}
          />
        </label>
      </div>

      <div className="sm-field">
        <div className="sm-field-k">你的判断</div>
        <div className="sm-radios" role="radiogroup" aria-label="这题你有几成把握">
          {SELF_REPORTS.map((item) => (
            <label className="sm-radio" key={item.value}>
              <input
                checked={selfReport === item.value}
                name="self-report"
                onChange={() => setSelfReport(item.value)}
                type="radio"
                value={item.value}
              />
              <span>{item.label}</span>
            </label>
          ))}
        </div>
        <p className="sm-note sm-note-quiet" style={{ marginTop: 10 }}>
          这一项不影响对错判断，只用来区分真会和蒙对。答案对、过程缺一环，是最需要被看见的一种。
        </p>
      </div>

      {localError ?? error ? (
        <p className="sm-alert" role="alert">
          {localError ?? error}
        </p>
      ) : null}

      <div>
        <button
          className="sm-act"
          disabled={busy}
          onClick={ripple}
          ref={submitRef}
          type="submit"
        >
          {busy ? "正在拆题……" : "开始诊断"}
          <span aria-hidden="true" className="sm-ar">
            →
          </span>
        </button>
      </div>

      {busy ? <p className="sm-busy">正在读你的过程，不打断你……</p> : null}

      <p className="sm-disclaimer">
        当前只支持高中数学「函数与导数」的示例题。
        <button className="sm-bail" onClick={fillSample} type="button">
          没有题目？填入示例题
        </button>
      </p>
    </form>
  );
}