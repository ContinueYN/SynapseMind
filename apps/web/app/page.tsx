"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { GlassCard } from "@/components/GlassCard";
import { ProblemForm } from "@/components/ProblemForm";
import { createSession } from "@/src/lib/api/client";
import type { CreateSessionInput } from "@/src/lib/api/types";

const LOOP = [
  ["交题", "题目、答案、过程。写不到最后也没关系，卡住的那一行最有用。"],
  ["拆题", "把这题拆成读题、求导、分情况、收尾四步，只给路径，不给答案。"],
  ["追问", "一次只问一个能回答的问题，2–6 轮，问到的是你自己的话。"],
  ["定位", "一句话说清断在哪一步，附上证据和已经排除掉的可能。"],
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
    <div>
      <section className="sm-hero">
        <p className="sm-eyebrow">单题诊断 · 学习模式</p>
        <h1 className="sm-h1">
          把题给我，<span className="sm-glaze">写到哪算哪</span>。
        </h1>
        <p className="sm-lede">
          不用写完整。写到卡住的那一行停下就行——那个位置比答案有用。
        </p>
      </section>

      <div className="sm-panel">
        <GlassCard>
          <ProblemForm busy={busy} error={error} onSubmit={start} />
        </GlassCard>
      </div>

      <section className="sm-band">
        <h2 className="sm-h2">四段，走完一轮</h2>
        <div className="sm-cols" data-cols="4">
          {LOOP.map(([title, text], index) => (
            <div className="sm-col" key={title}>
              <div className="sm-ch">
                {String(index + 1).padStart(2, "0")} · {title}
              </div>
              <p>{text}</p>
            </div>
          ))}
        </div>
        <p className="sm-fine">
          前 3 轮不给最终答案。每轮都有一个「我还是不懂」，可以往下退一级提示，而不是卡住。
        </p>
      </section>
    </div>
  );
}