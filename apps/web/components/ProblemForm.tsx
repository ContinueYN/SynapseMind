"use client";

import { FormEvent, useState } from "react";

import type { CreateSessionInput } from "@/src/lib/api/types";

interface ProblemFormProps {
  busy: boolean;
  error: string | null;
  onSubmit: (input: CreateSessionInput) => Promise<void>;
}

const SAMPLE_PROBLEM =
  "已知函数 f(x)=ln x - a x，a∈R。若 f(x)≤0 对任意 x>0 恒成立，求 a 的取值范围。";
const SAMPLE_WORK =
  "定义域 x>0。f'(x)=1/x-a，令 f'(x)=0 得 x=1/a。a>0 时，最大值为 f(1/a)=-ln a-1≤0，所以 a≥1/e。";

export function ProblemForm({ busy, error, onSubmit }: ProblemFormProps) {
  const [problemText, setProblemText] = useState(SAMPLE_PROBLEM);
  const [answer, setAnswer] = useState("a≥1/e");
  const [work, setWork] = useState(SAMPLE_WORK);
  const [selfReport, setSelfReport] =
    useState<NonNullable<CreateSessionInput["attempt"]["self_report"]>>("wrong");
  const [localError, setLocalError] = useState<string | null>(null);

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
        self_report: selfReport,
      },
      mode: "learning",
    });
  }

  return (
    <form className="problem-form" onSubmit={handleSubmit}>
      <div className="form-heading">
        <p className="eyebrow">交题 · 不是交作业</p>
        <h1>把题和你的过程放进来。</h1>
        <p>
          答案对错不重要；重要的是你写到哪一步、哪里开始不确定。系统只追问，不先讲答案。
        </p>
      </div>

      <label className="field">
        <span>题目</span>
        <textarea
          onChange={(event) => setProblemText(event.target.value)}
          rows={4}
          value={problemText}
        />
      </label>

      <div className="field-row">
        <label className="field">
          <span>你的答案</span>
          <input
            onChange={(event) => setAnswer(event.target.value)}
            placeholder="例如 a≥1/e，或写“不会”"
            value={answer}
          />
        </label>
        <label className="field compact">
          <span>你的判断</span>
          <select
            onChange={(event) =>
              setSelfReport(event.target.value as typeof selfReport)
            }
            value={selfReport}
          >
            <option value="wrong">做错了</option>
            <option value="unsure">不确定</option>
            <option value="correct_but_guessed">对了但有点蒙</option>
            <option value="no_idea">完全不会</option>
          </select>
        </label>
      </div>

      <label className="field">
        <span>你的过程（越具体越好）</span>
        <textarea
          onChange={(event) => setWork(event.target.value)}
          rows={7}
          value={work}
        />
      </label>

      {localError || error ? (
        <p className="form-error" role="alert">
          {localError ?? error}
        </p>
      ) : null}

      <button className="primary-button" disabled={busy} type="submit">
        {busy ? "正在拆题……" : "开始诊断"}
      </button>
      <p className="form-note">
        当前只支持高中数学「函数与导数」的示例题；换题会在 M2 接入题型识别。
      </p>
    </form>
  );
}