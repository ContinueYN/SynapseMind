"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

import { useGlass } from "@/components/useGlass";
import type { Probe } from "@/src/lib/api/types";

interface ProbeCardProps {
  probe: Probe;
  /** 这是第几问（已回答轮次 + 1） */
  turn: number;
  busy: boolean;
  onSelect: (optionId: string, optionText: string) => void;
  onUnknown: () => void;
  onExit: () => void;
}

const LETTERS = ["A", "B", "C", "D", "E", "F"];

function whyText(probe: Probe): string {
  if (probe.reason_code === "LEAK_FALLBACK") {
    return "这一问原本可能带出答案，被答案防护层换成了一道更上位的条件题。";
  }
  if (probe.action === "hint") {
    return "上一问没问出来，所以换成同一个点的另一种问法：台阶低一级。";
  }
  if (probe.action === "confirm") {
    return "这一问用来确认上一轮的判断，答完就能定位。";
  }
  return "一次只问一个能回答的问题。这一问的答案，决定下一问问什么。";
}

const ACTION_TAG = {
  ask: "这一问在分辨",
  hint: "退一级台阶",
  confirm: "确认上一轮",
} as const;

export function ProbeCard({ probe, turn, busy, onSelect, onUnknown, onExit }: ProbeCardProps) {
  const options = useMemo(() => probe.options ?? [], [probe.options]);
  const [typed, setTyped] = useState("");
  const [picked, setPicked] = useState<number | null>(null);
  const [whyPinned, setWhyPinned] = useState(false);
  const [whyHeld, setWhyHeld] = useState(false);
  const [exitArmed, setExitArmed] = useState(false);

  const whyOpen = whyPinned || whyHeld;

  useEffect(() => {
    setPicked(null);
    setTyped("");
    setWhyPinned(false);
    setExitArmed(false);
  }, [probe.question]);

  /* 退出是不可逆动作：第一次点只举手，第二次才真的走 */
  useEffect(() => {
    if (!exitArmed) return;
    const timer = window.setTimeout(() => setExitArmed(false), 4000);
    return () => window.clearTimeout(timer);
  }, [exitArmed]);

  /* 数字键直接作答；按住 H 看这一问在分辨什么 */
  useEffect(() => {
    function isTyping(event: KeyboardEvent) {
      const tag = (event.target as HTMLElement | null)?.tagName;
      return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.metaKey || event.ctrlKey || event.altKey || isTyping(event)) return;

      if (event.key.toLowerCase() === "h" && !event.repeat) {
        setWhyHeld(true);
        return;
      }

      if (busy || options.length === 0) return;
      const index = Number.parseInt(event.key, 10) - 1;
      if (!Number.isInteger(index) || index < 0 || index >= options.length) return;

      event.preventDefault();
      setPicked(index);
      onSelect(LETTERS[index] ?? "A", options[index]);
    }

    function onKeyUp(event: KeyboardEvent) {
      if (event.key.toLowerCase() === "h") setWhyHeld(false);
    }

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [busy, onSelect, options]);

  function choose(index: number) {
    if (busy) return;
    setPicked(index);
    onSelect(LETTERS[index] ?? "A", options[index]);
  }

  function submitTyped(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = typed.trim();
    if (!text || busy) return;
    onSelect("", text);
  }

  /* 冷光与柔光跟着指针走：直接改 CSS 变量，不触发重渲染 */
  const glass = useGlass<HTMLDivElement>();

  return (
    <div
      aria-busy={busy}
      aria-live="polite"
      className="sm-probe"
      onPointerLeave={glass.onPointerLeave}
      onPointerMove={glass.onPointerMove}
      ref={glass.ref}
    >
      <span aria-hidden="true" className="sm-sheen" />
      <div className="sm-probe-top">
        <span className="sm-probe-tag">
          第 {turn} 问 · {ACTION_TAG[probe.action] ?? ACTION_TAG.ask}
          {probe.hint_level > 0 ? ` · 第 ${probe.hint_level} 级` : ""}
        </span>
        <button
          aria-expanded={whyOpen}
          className="sm-link sm-link-quiet"
          onClick={() => setWhyPinned((open) => !open)}
          type="button"
        >
          {whyOpen ? "收起" : "为什么问这个"}
        </button>
      </div>

      <p className="sm-q">{probe.question}</p>

      <div className="sm-why" data-open={whyOpen}>
        <div className="sm-why-in">
          <p>{whyText(probe)}</p>
        </div>
      </div>

      {options.length > 0 ? (
        <>
          <div aria-label="回答选项" className="sm-opts" role="group">
            {options.map((option, index) => (
              <button
                aria-pressed={picked === index}
                className="sm-opt"
                data-picked={picked === index}
                disabled={busy}
                key={option}
                onClick={() => choose(index)}
                type="button"
              >
                <span aria-hidden="true" className="sm-opt-key">
                  {index + 1}
                </span>
                <span className="sm-opt-body">{option}</span>
                <svg
                  aria-hidden="true"
                  className="sm-opt-mark"
                  fill="none"
                  viewBox="0 0 16 16"
                >
                  <path
                    d="M3 8.4 6.2 11.6 13 4.6"
                    stroke="currentColor"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth="1.6"
                  />
                </svg>
              </button>
            ))}
          </div>
          <p className="sm-keys">
            按 <kbd>1</kbd>–<kbd>{options.length}</kbd> 直接作答 · 按住 <kbd>H</kbd> 看这一问在分辨什么
          </p>
        </>
      ) : (
        <form className="sm-opts" onSubmit={submitTyped}>
          <label className="sm-f">
            <span className="sm-f-label">直接回答</span>
            <input
              disabled={busy}
              onChange={(event) => setTyped(event.target.value)}
              placeholder="一句话就行"
              type="text"
              value={typed}
            />
          </label>
          <div style={{ padding: "18px 0 4px" }}>
            <button className="sm-cta" disabled={busy || !typed.trim()} type="submit">
              {busy ? "正在判断" : "提交回答"}
              <span aria-hidden="true" className="sm-ar">
                →
              </span>
            </button>
          </div>
        </form>
      )}

      <div className="sm-probe-foot">
        <button className="sm-link" disabled={busy} onClick={onUnknown} type="button">
          我还是不懂
        </button>
        <button
          className="sm-link sm-link-quiet"
          data-armed={exitArmed}
          disabled={busy}
          onClick={() => {
            if (!exitArmed) {
              setExitArmed(true);
              return;
            }
            setExitArmed(false);
            onExit();
          }}
          type="button"
        >
          {exitArmed ? "再点一次：退出后本轮不出卡" : "退出学习模式"}
        </button>
        <span className="sm-probe-foot-note">
          {busy ? "正在判断，不打断你" : "答完自动进入下一问"}
        </span>
      </div>
    </div>
  );
}