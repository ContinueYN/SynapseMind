"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useState } from "react";

import { CluePreview } from "@/components/CluePreview";
import { Plane } from "@/components/Plane";
import { EMPTY_DRAFT, ProblemForm, type Draft } from "@/components/ProblemForm";
import { Reveal } from "@/components/Reveal";
import { Surface } from "@/components/Surface";
import { useTiltZone } from "@/components/useTilt";
import { createSession, isUnauthorized } from "@/src/lib/api/client";
import type { CreateSessionInput } from "@/src/lib/api/types";
import {
  PAPERS,
  PRINCIPLES,
  RESEARCH_BOUNDARY,
  papersFor,
} from "@/src/lib/research/papers";
import { handOffSession } from "@/src/lib/session-handoff";

/* 四步：只写这一步"给什么"，不写"意味着什么" */
const LOOP = [
  ["交题", "题目、答案、你写到的最后一行。"],
  ["拆题", "拆成读题、条件、执行、校验四段，先看路径。"],
  ["追问", "一次问一个，你用自己的话答。"],
  ["定位", "断在哪一步、凭哪几句、哪些已经排除。"],
] as const;

const EDGE = [
  ["给你", "卡在哪一步，依据是你写过的哪几句，下次先练什么。"],
  ["不给", "过程中的最终解法、分数、排名，以及任何能力或医学评估。"],
  ["要你", "题目、一个答案、写到的那一行。空着的格子会标出来。"],
] as const;

const META = [
  ["一轮", "6–8 分钟"],
  ["追问", "2–6 轮"],
  ["拿到", "一张卡点卡"],
] as const;

/* 卡点卡的四个字段：像书末的索引，一条引线连到它回答的问题 */
const INDEX = [
  ["一句话结论", "断在哪一步"],
  ["依据", "你写过的哪几句"],
  ["已经排除", "哪些可能不必再试"],
  ["三步处置", "下一次先练什么"],
] as const;

/* 示例卡：用第一道示例题（f(x)=ln x−ax）真跑出来的样子，不是占位符 */
const SAMPLE_CARD = [
  ["一句话结论", "卡在「先定 a 的符号」这一步。"],
  ["依据", "你写了 f′(x)=1/x−a，之后直接把 x=1/a 当成了最大值点。"],
  ["已经排除", "定义域漏 x>0（你写了）；求导写错（这一步是对的）。"],
  ["三步处置", "先分 a>0、a≤0 各写一行 → 画 a>0 的单调表 → 用 a=1/e 回代验算。"],
] as const;

export default function HomePage() {
  const router = useRouter();
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /* 光标停在哪个字段，左边枝干上对应的那一格就亮一下 */
  const [hotField, setHotField] = useState<string | null>(null);
  /* 一段区域里所有 data-tilt 的玻璃砖共用一套指针监听 */
  const tiltRef = useTiltZone<HTMLDivElement>();

  async function start(input: CreateSessionInput) {
    setBusy(true);
    setError(null);
    try {
      const session = await createSession(input);
      handOffSession(session);
      router.push(`/diagnose/${session.session_id}`);
    } catch (caught) {
      if (isUnauthorized(caught)) {
        // The API gate says there is no session; the form itself is not wrong.
        // Carry the user to /login and come back to the same entry point.
        setBusy(false);
        router.push("/login?next=/");
        return;
      }
      setError(caught instanceof Error ? caught.message : "开始失败，请稍后重试。");
      setBusy(false);
    }
  }

  return (
    <div ref={tiltRef}>
      {/* 第一层：字标与交题板是两块玻璃，交题板往下错 40px */}
      <section className="sm-hero">
        <Plane className="sm-hero-lead">
          <p className="sm-eyebrow">
            <span aria-hidden="true" className="sm-dot" />
            通用问题诊断 · 不是只做数学
          </p>

          <h1 className="sm-display">
            把问题给我，
            <span className="sm-display-2">写到哪算哪</span>
          </h1>

          <p className="sm-lede">
            数学题、代码报错、写作草稿、要不要换工作——同一个入口。
            过程写一半也行，停在哪一行，第一问就从哪一行开始；
            判断不出领域就按通用问题处理，不拦你。
          </p>

          <CluePreview draft={draft} hotId={hotField} />

          <p className="sm-meta-line">
            {META.map(([label, value], index) => (
              <span key={label}>
                {index > 0 ? <i aria-hidden="true" className="sm-meta-sep" /> : null}
                {label} <b>{value}</b>
              </span>
            ))}
          </p>
        </Plane>

        <div className="sm-hero-side">
          <Surface>
            <ProblemForm
              busy={busy}
              error={error}
              onChange={setDraft}
              onFocusField={setHotField}
              onSubmit={start}
              value={draft}
            />
          </Surface>
        </div>
      </section>

      {/* 第二层：每一段坐在自己的玻璃板上，页签探出板的上缘 */}
      <Reveal className="sm-flow">
        <Plane>
          <h2 className="sm-label">
            <em>01</em>
            怎么走
          </h2>

          <p className="sm-statement">四步。你只在第三步开口。</p>

          <div className="sm-track">
            <span aria-hidden="true" className="sm-track-rail" />
            {LOOP.map(([title, text], index) => (
              <div className="sm-step sm-tile" data-tilt="" key={title}>
                <span aria-hidden="true" className="sm-step-dot" />
                <span className="sm-step-n">{`0${index + 1}`}</span>
                <b className="sm-step-h">{title}</b>
                <p>{text}</p>
              </div>
            ))}
          </div>
        </Plane>
      </Reveal>

      <Reveal className="sm-flow sm-flow--right">
        <Plane>
          <h2 className="sm-label">
            <em>02</em>
            你会拿到
          </h2>

          <p className="sm-statement">四个字段，没有分数。</p>

          <div className="sm-index">
            {INDEX.map(([key, value]) => (
              <p key={key}>
                <b>{key}</b>
                <i aria-hidden="true" />
                <span>{value}</span>
              </p>
            ))}
          </div>
        </Plane>
      </Reveal>

      <Reveal className="sm-flow sm-flow--narrow">
        <Plane>
          <h2 className="sm-label">
            <em>03</em>
            界线
          </h2>

          <p className="sm-statement">它只做一件事：定位。</p>

          <div className="sm-note-list">
            {EDGE.map(([title, text]) => (
              <div className="sm-note-item sm-tile" data-tilt="" key={title}>
                <b className="sm-note-k">{title}</b>
                <p>{text}</p>
              </div>
            ))}
          </div>
        </Plane>
      </Reveal>

      <Reveal className="sm-flow sm-flow--center">
        <Plane>
          <h2 className="sm-label">
            <em>04</em>
            一张卡长什么样
          </h2>

          <p className="sm-statement">这是示例题跑完之后的原样。</p>

          <div className="sm-cardmock">
            <div className="sm-cardmock-head">
              <span className="sm-cardmock-tag">示例</span>
              <b>函数与导数 · f(x)=ln x−ax</b>
              <span className="sm-cardmock-conf">把握 82%</span>
            </div>
            <dl className="sm-cardmock-rows">
              {SAMPLE_CARD.map(([key, value]) => (
                <div key={key}>
                  <dt>{key}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          </div>
        </Plane>
      </Reveal>
    <Reveal className="sm-flow sm-flow--narrow">
        <Plane>
          <h2 className="sm-label">
            <em>05</em>
            研究依据 / Research basis
          </h2>

          <p className="sm-statement">借的是机制，不借效果背书。</p>

          <p className="sm-lede sm-research-lede">
            每条原则只写三件事：借的机制、对应的设计动作、以及不声称什么。
            文献按 DOI 链到原文；引用解释设计来源，不是疗效证据。
          </p>

          <p className="sm-research-facts">
            <span>
              <b>{PAPERS.length}</b> 篇公开文献
            </span>
            <span>
              <b>{PRINCIPLES.length}</b> 条设计原则
            </span>
            <span>
              <b>0</b> 项效果背书
            </span>
          </p>

          <div className="sm-research">
            {PRINCIPLES.map((principle, index) => (
              <article
                className="sm-tile sm-research-card"
                data-tilt=""
                key={principle.id}
              >
                <header className="sm-research-head">
                  <span className="sm-research-n">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <h3 className="sm-research-h">{principle.label}</h3>
                  <span className="sm-research-en">{principle.english}</span>
                </header>

                <p className="sm-research-mech">{principle.mechanism}</p>

                <ul className="sm-research-refs">
                  {papersFor(principle).map((paper) => (
                    <li key={paper.id}>
                      <a
                        className="sm-research-ref"
                        href={paper.url}
                        rel="noreferrer"
                        target="_blank"
                      >
                        <span className="sm-research-cite">
                          <b>{paper.authors}</b> ({paper.year}).{" "}
                          <cite>{paper.title}</cite>. <span>{paper.venue}</span>
                        </span>
                        <span className="sm-research-doi">
                          doi:{paper.doi}
                          <span aria-hidden="true"> ↗</span>
                        </span>
                      </a>
                      <p className="sm-research-borrow">
                        <span aria-hidden="true">借用 · </span>
                        {paper.borrow}
                      </p>
                    </li>
                  ))}
                </ul>

                <p className="sm-research-boundary">
                  <span>不声称</span>
                  {principle.notClaiming}
                </p>
              </article>
            ))}
          </div>

          <p className="sm-research-note" role="note">
            <b>{RESEARCH_BOUNDARY}</b>
            <span>
              引用只说明「为什么这样设计」，不代表我们复现了论文结果，
              也不构成对任何人的效果承诺。
            </span>
          </p>

          <p className="sm-ground-more">
            <Link href="/science">五条机制与逐条引用 →</Link>
            <span aria-hidden="true"> · </span>
            <Link href="/cases">六段演示记录 →</Link>
          </p>
        </Plane>
    </Reveal>
    </div>
  );
}