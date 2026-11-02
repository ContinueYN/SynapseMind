"use client";

import { useCallback, useEffect, useMemo, useRef, type PointerEvent } from "react";

/**
 * 玻璃跟手：把指针位置写进 CSS 变量，再给一点点倾斜。
 *
 * - `--mx/--my`：边框冷光的位置
 * - `--lx/--ly`：玻璃表面那团柔光的位置
 * - `--rx/--ry`：最多 1.5° / 1.05° 的倾斜（物理上是"光在弯的玻璃上走"）
 *
 * 和 v4 的区别：不再把指针位置**直接**写进去，而是每帧向目标追 18%（指数逼近）。
 * 光是"滑"过去的，指针停住后自己收口——生硬感主要来自"瞬时到位"。
 * 全部只写 style，不进 React state；触屏与 reduce-motion 下完全不跟手。
 */
export function useGlass<T extends HTMLElement>(options: { tilt?: number } = {}) {
  const tilt = options.tilt ?? 1;
  const ref = useRef<T>(null);
  const frame = useRef(0);
  const goal = useRef({ x: 0.5, y: 0.5 });
  const shown = useRef({ x: 0.5, y: 0.5 });

  const still = useMemo(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    [],
  );

  const write = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const { x, y } = shown.current;
    el.style.setProperty("--mx", `${(x * 100).toFixed(2)}%`);
    el.style.setProperty("--my", `${(y * 100).toFixed(2)}%`);
    el.style.setProperty("--lx", `${(14 + x * 72).toFixed(2)}%`);
    el.style.setProperty("--ly", `${(-6 + y * 88).toFixed(2)}%`);
    el.style.setProperty("--ry", `${((x - 0.5) * 3 * tilt).toFixed(3)}deg`);
    el.style.setProperty("--rx", `${((0.5 - y) * 2.1 * tilt).toFixed(3)}deg`);
  }, [tilt]);

  /* 一帧追 18%，差值小于 0.08% 就停：光不会无限抖动，也不会突然跳到位 */
  const tick = useCallback(() => {
    frame.current = 0;
    const dx = goal.current.x - shown.current.x;
    const dy = goal.current.y - shown.current.y;

    if (Math.abs(dx) < 0.0008 && Math.abs(dy) < 0.0008) {
      shown.current = { ...goal.current };
      write();
      return;
    }

    shown.current = {
      x: shown.current.x + dx * 0.18,
      y: shown.current.y + dy * 0.18,
    };
    write();
    frame.current = requestAnimationFrame(tick);
  }, [write]);

  const schedule = useCallback(() => {
    if (!frame.current) frame.current = requestAnimationFrame(tick);
  }, [tick]);

  const onPointerMove = useCallback(
    (event: PointerEvent<T>) => {
      if (still || event.pointerType === "touch") return;
      const el = ref.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      goal.current = {
        x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
        y: Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height)),
      };
      schedule();
    },
    [schedule, still],
  );

  const onPointerLeave = useCallback(() => {
    goal.current = { x: 0.5, y: 0.5 };
    schedule();
  }, [schedule]);

  useEffect(
    () => () => {
      if (frame.current) cancelAnimationFrame(frame.current);
    },
    [],
  );

  return { ref, onPointerMove, onPointerLeave };
}