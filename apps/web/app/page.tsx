"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ProblemForm } from "@/components/ProblemForm";
import { createSession } from "@/src/lib/api/client";
import type { CreateSessionInput } from "@/src/lib/api/types";

const STEPS = [
  ["01", "拆题", "把题目拆成读题、概念、条件、策略、执行、校验。"],
  ["02", "对齐", "把你的过程贴到解法图上，找第一处偏离。"],
  ["03", "追问", "一次只问一个可回答的问题，用反例和边界逼出真实理解。"],
  ["04", "定位", "给一张带证据的卡点卡，不是成绩单。"],
];

export default function HomePage() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start(input: CreateSessionInput) {
    setBusy(true);
    setError(null);
    try {
      const session = await createSession(input);
      router.push(`/diagnose/${session.session_id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "开始失败，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="home-grid">
      <section className="home-intro">
        <p className="eyebrow">单题诊断 · 不是题库</p>
        <h1>
          答案对错不重要，
          <br />
          你卡在哪一步才重要。
        </h1>
        <p className="lede">
          交一道你不会或做错的题，加上你的答案和过程。系统用 2–6 轮追问，找到最早断掉的认知动作，给一张卡点卡。
        </p>
        <div className="step-list">
          {STEPS.map(([number, title, text]) => (
            <article className="step" key={number}>
              <span className="step-number">{number}</span>
              <div>
                <h2>{title}</h2>
                <p>{text}</p>
              </div>
            </article>
          ))}
        </div>
      </section>
      <ProblemForm busy={busy} error={error} onSubmit={start} />
    </div>
  );
}