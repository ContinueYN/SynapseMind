"use client";

import { FormEvent, useState } from "react";

import SpotlightCard from "@/components/reactbits/SpotlightCard";
import StarBorder from "@/components/reactbits/StarBorder";
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
    <SpotlightCard
      aria-labelledby="intake-title"
      className="intake-card"
      id="intake"
      intensity={0.22}
      spotlightColor="rgba(94, 234, 212, 0.6)"
      spotlightSize={460}
      theme="dark"
    >
      <form className="problem-form" onSubmit={handleSubmit}>
        <div className="form-heading">
          <p className="eyebrow">交题 · 不是交作业</p>
          <h2 id="intake-title">把题和你的过程放进来。</h2>
          <p>
            答案对错不重要；重要的是你写到哪一步、哪里开始不确定。
            系统只追问，不先讲答案。
          </p>
        </div>

        <label className="field">
          <span>
            题目 <em>01</em>
          </span>
          <textarea
            onChange={(event) => setProblemText(event.target.value)}
            rows={4}
            value={problemText}
          />
        </label>

        <div className="field-row">
          <label className="field">
            <span>
              你的答案 <em>02</em>
            </span>
            <input
              onChange={(event) => setAnswer(event.target.value)}
              placeholder="例如 a≥1/e，或写“不会”"
              value={answer}
            />
          </label>
          <label className="field compact">
            <span>
              你的判断 <em>03</em>
            </span>
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
          <span>
            你的过程 <em>04</em>
          </span>
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

        <StarBorder
          as="button"
          backgroundColor="#0b1220"
          className="submit-star"
          color="#5eead4"
          disabled={busy}
          duration={5}
          hover="brighten"
          radius={14}
          textColor="#f8fafc"
          thickness={2}
          trailColor="#818cf8"
          type="submit"
        >
          {busy ? "正在拆题……" : "开始诊断 →"}
        </StarBorder>

        <p className="form-note">
          当前只支持高中数学「函数与导数」的示例题；换题会在 M2 接入题型识别。
        </p>
      </form>
    </SpotlightCard>
  );
}