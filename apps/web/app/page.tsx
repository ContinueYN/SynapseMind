"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { CluePreview } from "@/components/CluePreview";
import { EMPTY_DRAFT, ProblemForm, type Draft } from "@/components/ProblemForm";
import { Reveal } from "@/components/Reveal";
import { Surface } from "@/components/Surface";
import { createSession } from "@/src/lib/api/client";
import type { CreateSessionInput } from "@/src/lib/api/types";
import { handOffSession } from "@/src/lib/session-handoff";

const LOOP = [
  ["交题", "题目、答案、过程。写不到最后也没关系，卡住的那一行最有用。"],
  ["拆题", "把这题拆成读题、概念、条件、执行、校验几步，只给路径，不给答案。"],
  ["追问", "一次只问一个能回答的问题，2–6 轮，问到的是你自己的话。"],
  ["定位", "一句话说清断在哪一步，附上证据和已经排除掉的可能。"],
] as const;

const EDGE = [
  ["只做定位", "告诉你卡在哪一步、依据是你写过的哪几句、下一步练什么。"],
  ["不给答案", "不出现最终解法，不产分数、不排名，不做智力或医学评估。"],
  ["要你写一点", "题目、答案、写到的那一行。写不全也能开始，空着的格子会标出来。"],
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

export default function HomePage() {
  const router = useRouter();
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /* 光标停在哪个字段，左边枝干上对应的那一格就亮一下 */
  const [hotField, setHotField] = useState<string | null>(null);

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
    <div className="sm-page">
      <section className="sm-hero">
        <div className="sm-hero-lead">
          <p className="sm-eyebrow">
            <span aria-hidden="true" className="sm-dot" />
            单题诊断 · 学习模式
          </p>

          <h1 className="sm-display">
            把题给我，
            <span className="sm-display-2">写到哪算哪</span>
          </h1>

          <p className="sm-lede">
            不用写完整。写到卡住的那一行停下就行——那个位置比答案有用。
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
        </div>

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

      <Reveal className="sm-flow">
        <h2 className="sm-label">
          <em>01</em>
          怎么走
        </h2>

        <p className="sm-statement">四步里，只有第三步是你自己说话。</p>

        <div className="sm-track">
          {LOOP.map(([title, text], index) => (
            <div className="sm-step" key={title}>
              <span aria-hidden="true" className="sm-step-dot" />
              <span className="sm-step-n">{`0${index + 1}`}</span>
              <b className="sm-step-h">{title}</b>
              <p>{text}</p>
            </div>
          ))}
        </div>
      </Reveal>

      <Reveal className="sm-notes">
        <h2 className="sm-label">
          <em>02</em>
          你会拿到
        </h2>

        <p className="sm-statement">一张纸，四个字段，没有分数。</p>

        <div className="sm-index">
          {INDEX.map(([key, value]) => (
            <p key={key}>
              <b>{key}</b>
              <i aria-hidden="true" />
              <span>{value}</span>
            </p>
          ))}
        </div>
      </Reveal>

      <Reveal className="sm-notes">
        <h2 className="sm-label">
          <em>03</em>
          界线
        </h2>

        <p className="sm-statement">只给位置，不给答案。</p>

        {EDGE.map(([title, text]) => (
          <div className="sm-note-item" key={title}>
            <b className="sm-note-k">{title}</b>
            <p>{text}</p>
          </div>
        ))}
      </Reveal>

      <Reveal className="sm-quote">
        <blockquote>
          <p>一道题写到卡住的那一行，比十道题都做对，更有信息量。</p>
          <cite>诊断原则 · 只给位置，不给答案</cite>
        </blockquote>
      </Reveal>
    </div>
  );
}