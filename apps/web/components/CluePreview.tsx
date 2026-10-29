"use client";

import { Dendrite, type DendriteStop } from "@/components/Dendrite";
import type { Draft } from "@/components/ProblemForm";

/**
 * 交题页左侧的线索树：字段填一条，枝上就亮一点。
 * 光标停在哪一格，那一格也跟着亮——左边不是进度条，是这张纸上你已经写下的东西。
 */
export function CluePreview({
  draft,
  hotId = null,
}: {
  draft: Draft;
  hotId?: string | null;
}) {
  const slots = [
    { id: "problem", label: "题目", done: Boolean(draft.problem.trim()), hint: "你带来的那道题" },
    { id: "answer", label: "答案", done: Boolean(draft.answer.trim()), hint: "对错先不管" },
    { id: "work", label: "过程", done: Boolean(draft.work.trim()), hint: "卡住的那一行" },
    { id: "stuck", label: "卡点", done: Boolean(draft.stuckAt.trim()), hint: "可留空" },
  ];

  const filled = slots.filter((slot) => slot.done).length;
  const nextIndex = slots.findIndex((slot) => !slot.done);

  const stops: DendriteStop[] = slots.map((slot, index) => {
    const state = slot.done
      ? "done"
      : index === (nextIndex === -1 ? slots.length - 1 : nextIndex)
        ? "active"
        : "todo";
    return {
      id: slot.id,
      label: slot.label,
      detail: slot.done ? "已给出" : slot.hint,
      state,
      hot: slot.id === hotId,
    };
  });

  return (
    <div className="sm-clue">
      <Dendrite step={56} stops={stops} />
      <p className="sm-clue-cap">
        已写 <b>{filled}</b> 条。写得越具体，第一问问得越准。
      </p>
    </div>
  );
}