"use client";

import SpotlightCard from "@/components/reactbits/SpotlightCard";
import type { Probe } from "@/src/lib/api/types";

interface ProbeCardProps {
  probe: Probe;
  busy: boolean;
  onSelect: (optionId: string, optionText: string) => void;
  onUnknown: () => void;
  onExit: () => void;
}

const LETTERS = ["A", "B", "C", "D"];

export function ProbeCard({
  probe,
  busy,
  onSelect,
  onUnknown,
  onExit,
}: ProbeCardProps) {
  const options = probe.options ?? [];

  return (
    <SpotlightCard
      aria-busy={busy}
      aria-label="诊断追问"
      aria-live="polite"
      className="probe-card"
      intensity={0.16}
      role="region"
      spotlightColor="rgba(129, 140, 248, 0.55)"
      spotlightSize={420}
      theme="dark"
    >
      <div className="probe-topline">
        <p className="eyebrow">
          {probe.action === "hint" ? "换一种问法" : "只问一个问题"}
          {probe.hint_level > 0 ? ` · 提示 ${probe.hint_level}` : ""}
        </p>
        <span className="probe-ordinal">one question</span>
      </div>

      <h1 className="probe-question" id="probe-question">
        {probe.question}
      </h1>

      <div className="option-list" role="group" aria-label="回答选项">
        {options.map((option, index) => (
          <button
            className="option-button"
            disabled={busy}
            key={option}
            onClick={() => onSelect(LETTERS[index] ?? "A", option)}
            type="button"
          >
            <span className="option-letter">{LETTERS[index] ?? "A"}</span>
            <span>{option}</span>
            <span className="option-arrow" aria-hidden="true">
              ↗
            </span>
          </button>
        ))}
      </div>

      <div className="probe-actions">
        <button className="text-button" disabled={busy} onClick={onUnknown} type="button">
          我不知道，换个更具体的
        </button>
        <button className="text-button quiet" disabled={busy} onClick={onExit} type="button">
          直接退出学习模式
        </button>
      </div>
      {busy ? <p className="inline-status">正在判断，不打断你……</p> : null}
    </SpotlightCard>
  );
}