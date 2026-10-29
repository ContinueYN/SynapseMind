"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { Probe } from "@/src/lib/api/types";

interface ProbeCardProps {
  probe: Probe;
  busy: boolean;
  onSelect: (optionId: string, optionText: string) => void;
  onUnknown: () => void;
  onExit: () => void;
}

const LETTERS = ["A", "B", "C", "D", "E", "F"];

const ACTION_NOTE = {
  ask: "一次只问一个问题。这一问的答案，决定下一问问什么。",
  hint: "上一问没问出来，所以换一种问法——同一个点，台阶低一点。",
  confirm: "这一问用来确认上一轮的判断，答完就能定位。",
} as const;

export function ProbeCard({ probe, busy, onSelect, onUnknown, onExit }: ProbeCardProps) {
  const options = useMemo(() => probe.options ?? [], [probe.options]);
  const [typed, setTyped] = useState("");
  const [picked, setPicked] = useState<number | null>(null);

  const listRef = useRef<HTMLDivElement>(null);
  const blobRef = useRef<HTMLDivElement>(null);
  const seedRef = useRef<HTMLDivElement>(null);

  /** 液态药丸滑到第 i 行——位置按真实行高算，换字号也不会错位 */
  function moveTo(index: number) {
    const list = listRef.current;
    const blob = blobRef.current;
    const seed = seedRef.current;
    if (!list || !blob) return;

    const button = list.querySelectorAll<HTMLButtonElement>(".sm-opt")[index];
    if (!button) return;

    const top = button.offsetTop + 5;
    const height = Math.max(44, button.offsetHeight - 10);

    blob.style.transform = `translateY(${top}px)`;
    blob.style.height = `${height}px`;
    if (seed) {
      seed.style.transform = `translate(${button.offsetWidth * 0.42}px, ${top + height / 2 - 26}px)`;
    }
  }

  useEffect(() => {
    setPicked(null);
    setTyped("");
    moveTo(0);
  }, [probe.question]);

  /* 键盘作答：诊断要连答好几轮，每轮都去点鼠标，人会烦 */
  useEffect(() => {
    if (options.length === 0) return;

    function onKey(event: KeyboardEvent) {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const tag = (event.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;

      const index = Number.parseInt(event.key, 10) - 1;
      if (!Number.isInteger(index) || index < 0 || index >= options.length) return;

      event.preventDefault();
      setPicked(index);
      moveTo(index);
      onSelect(LETTERS[index] ?? "A", options[index]);
    }

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onSelect, options]);

  return (
    <div aria-busy={busy} aria-live="polite">
      <p className="sm-q">{probe.question}</p>

      {options.length > 0 ? (
        <div aria-label="回答选项" className="sm-opts" ref={listRef} role="group">
          <div aria-hidden="true" className="sm-goo">
            <div className="sm-goo-blob" ref={blobRef} />
            <div className="sm-goo-seed" ref={seedRef} />
          </div>

          {options.map((option, index) => (
            <button
              aria-pressed={picked === index}
              className="sm-opt"
              disabled={busy}
              key={option}
              onClick={() => {
                setPicked(index);
                moveTo(index);
                onSelect(LETTERS[index] ?? "A", option);
              }}
              onFocus={() => moveTo(index)}
              onPointerEnter={() => moveTo(index)}
              type="button"
            >
              <span className="sm-key" aria-hidden="true">
                {index + 1}
              </span>
              <span className="sm-opt-body">{option}</span>
              <span aria-hidden="true" className="sm-pick" />
            </button>
          ))}
        </div>
      ) : (
        <div className="sm-field">
          <label className="sm-field-k" htmlFor="probe-answer">
            直接回答
          </label>
          <label className="sm-inp">
            <input
              id="probe-answer"
              onChange={(event) => setTyped(event.target.value)}
              placeholder="一句话就行"
              type="text"
              value={typed}
            />
          </label>
        </div>
      )}

      <p className="sm-note" style={{ marginTop: 16 }}>
        {ACTION_NOTE[probe.action] ?? ACTION_NOTE.ask}
        {probe.hint_level > 0 ? ` 当前是第 ${probe.hint_level} 级提示。` : ""}
      </p>

      {options.length === 0 ? (
        <div style={{ marginTop: 18 }}>
          <button
            className="sm-act"
            disabled={busy || !typed.trim()}
            onClick={() => onSelect("typed", typed.trim())}
            type="button"
          >
            {busy ? "正在判断……" : "提交回答"}
            <span aria-hidden="true" className="sm-ar">
              →
            </span>
          </button>
        </div>
      ) : null}

      <div className="sm-card-acts">
        <button className="sm-bail" disabled={busy} onClick={onUnknown} type="button">
          我还是不懂
        </button>
        <button className="sm-bail" disabled={busy} onClick={onExit} type="button">
          退出学习模式
        </button>
      </div>

      {busy ? <p className="sm-busy">正在判断，不打断你……</p> : null}
    </div>
  );
}