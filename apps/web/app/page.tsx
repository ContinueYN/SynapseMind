"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { CluePreview } from "@/components/CluePreview";
import { Plane } from "@/components/Plane";
import { EMPTY_DRAFT, ProblemForm, type Draft } from "@/components/ProblemForm";
import { Reveal } from "@/components/Reveal";
import { Surface } from "@/components/Surface";
import { useTiltZone } from "@/components/useTilt";
import { createSession } from "@/src/lib/api/client";
import type { CreateSessionInput } from "@/src/lib/api/types";
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

const GROUNDS = [
  {
    tag: "突触可塑性",
    authors: "Citri & Malenka (2008)",
    text: "只借「成功提取会强化通路」的形状，不做脑测量。",
    doi: "10.1038/sj.npp.1301559",
  },
  {
    tag: "认知负荷",
    authors: "Sweller (1988)",
    text: "先降低外在负荷，再一次只给一个最小动作。",
    doi: "10.1207/s15516709cog1202_4",
  },
  {
    tag: "反馈",
    authors: "Hattie & Timperley (2007)",
    text: "反馈指向任务与下一步，不指向「你这个人」。",
    doi: "10.3102/003465430298487",
  },
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
            数学 · 物理 · 语文 · 自动识别
          </p>

          <h1 className="sm-display">
            把题给我，
            <span className="sm-display-2">写到哪算哪</span>
          </h1>

          <p className="sm-lede">
            过程写一半也行。停在哪一行，第一问就从哪一行开始。
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
            依据
          </h2>

          <p className="sm-statement">类比有出处，效果不借背书。</p>

          <div className="sm-grounds">
            {GROUNDS.map((ground) => (
              <a
                className="sm-ground sm-tile"
                href={`https://doi.org/${ground.doi}`}
                key={ground.doi}
                rel="noreferrer"
                target="_blank"
              >
                <span className="sm-ground-k">{ground.tag}</span>
                <b>{ground.authors}</b>
                <span>{ground.text}</span>
                <em>doi:{ground.doi}</em>
              </a>
            ))}
          </div>

          <p className="sm-fine">
            这些文献只解释设计形状：怎么降低负荷、怎么给反馈、为什么用「强化」作类比。
            我们没有做对照实验，也没有延迟正确率；不把类比写成神经测量，也不承诺提分。
          </p>
        </Plane>
      </Reveal>
    </div>
  );
}