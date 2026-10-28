"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ProblemForm } from "@/components/ProblemForm";
import GradientText from "@/components/reactbits/GradientText";
import SpotlightCard from "@/components/reactbits/SpotlightCard";
import { createSession } from "@/src/lib/api/client";
import type { CreateSessionInput } from "@/src/lib/api/types";

const STEPS = [
  {
    number: "01",
    title: "拆题",
    text: "把题目拆成读题、概念、条件、策略、执行、校验。",
    color: "rgba(94, 234, 212, 0.6)",
  },
  {
    number: "02",
    title: "对齐",
    text: "把你的过程贴到解法图上，找第一处偏离。",
    color: "rgba(129, 140, 248, 0.6)",
  },
  {
    number: "03",
    title: "追问",
    text: "一次只问一个可回答的问题，用反例和边界逼出真实理解。",
    color: "rgba(251, 191, 36, 0.55)",
  },
  {
    number: "04",
    title: "定位",
    text: "给一张带证据的卡点卡，不是成绩单。",
    color: "rgba(244, 114, 182, 0.55)",
  },
];

const TRACE = [
  ["读题", "题目：f(x)=ln x - ax，a∈R", "done"],
  ["条件转译", "对所有 x>0 成立 → 最大值 ≤ 0", "done"],
  ["参数分类", "a>0 走完，a≤0 没有单独检查", "open"],
  ["校验", "回代边界 a=0", "waiting"],
] as const;

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
    <div className="home-page">
      <section className="home-grid">
        <div className="home-intro">
          <p className="eyebrow">
            <span className="pulse-dot" aria-hidden="true" />
            单题诊断 · 不是题库
          </p>

          <h1 className="hero-title">
            答案对错不重要，
            <br />
            <GradientText
              animationSpeed={7}
              colors={["#5eead4", "#a5b4fc", "#f0abfc"]}
              direction="horizontal"
              glow={0.35}
              variant="flow"
            >
              你卡在哪一步才重要。
            </GradientText>
          </h1>

          <p className="lede">
            交一道你不会或做错的题，加上你的答案和过程。系统用 2–6 轮追问，
            找到最早断掉的认知动作，给一张卡点卡。
          </p>

          <div className="hero-stats" aria-label="诊断概览">
            <div>
              <strong>2–6</strong>
              <span>轮追问</span>
            </div>
            <div>
              <strong>1</strong>
              <span>张卡点卡</span>
            </div>
            <div>
              <strong>3 min</strong>
              <span>最小干预</span>
            </div>
          </div>

          <div className="trace-preview" aria-label="诊断轨迹示例">
            <div className="trace-header">
              <span>诊断轨迹</span>
              <span className="trace-live">
                <span className="pulse-dot" aria-hidden="true" />
                find the first break
              </span>
            </div>
            <ol>
              {TRACE.map(([title, detail, status], index) => (
                <li className={`trace-step ${status}`} key={title}>
                  <span className="trace-index">{String(index + 1).padStart(2, "0")}</span>
                  <div>
                    <strong>{title}</strong>
                    <span>{detail}</span>
                  </div>
                  <span className="trace-status">{status === "open" ? "待验证" : ""}</span>
                </li>
              ))}
            </ol>
          </div>
        </div>

        <ProblemForm busy={busy} error={error} onSubmit={start} />
      </section>

      <section className="process-section" id="how-it-works">
        <div className="section-heading">
          <p className="eyebrow">HOW IT WORKS</p>
          <h2>把“不会”拆成可验证的动作。</h2>
          <p>不急着讲答案；先找到你从哪一步开始偏离。</p>
        </div>

        <div className="step-grid">
          {STEPS.map((step) => (
            <SpotlightCard
              className="step-card"
              intensity={0.18}
              key={step.number}
              spotlightColor={step.color}
              spotlightSize={280}
              theme="dark"
            >
              <span className="step-number">{step.number}</span>
              <h3>{step.title}</h3>
              <p>{step.text}</p>
            </SpotlightCard>
          ))}
        </div>
      </section>
    </div>
  );
}